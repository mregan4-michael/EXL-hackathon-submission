// fxhost: JSON-lines bridge to Microsoft's Power Fx parser and interpreter.
// Requests:  {"op":"parse","formula":"..."} | {"op":"eval","formula":"...","vars":{...}}
// Values:    number | string | bool | null | {"$date":"yyyy-MM-dd"} | {record} | [table]
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.PowerFx;
using Microsoft.PowerFx.Syntax;
using Microsoft.PowerFx.Types;

var stdin = Console.In;
var stdout = Console.Out;
string? line;
while ((line = stdin.ReadLine()) != null)
{
    if (string.IsNullOrWhiteSpace(line)) continue;
    JsonObject resp;
    try
    {
        var req = JsonNode.Parse(line)!.AsObject();
        var op = (string)req["op"]!;
        var formula = (string)req["formula"]!;
        resp = op switch
        {
            "parse" => FxHost.Parse(formula),
            "eval" => FxHost.Eval(formula, req["vars"] as JsonObject),
            _ => new JsonObject { ["ok"] = false, ["error"] = $"unknown op {op}" },
        };
        if (req["id"] is JsonNode id) resp["id"] = id.DeepClone();
    }
    catch (Exception ex)
    {
        resp = new JsonObject { ["ok"] = false, ["error"] = ex.GetType().Name + ": " + ex.Message };
    }
    stdout.WriteLine(resp.ToJsonString());
    stdout.Flush();
}

internal static class FxHost
{
    private static readonly ParserOptions ParseOpts = new() { AllowsSideEffects = true };

    public static JsonObject Parse(string formula)
    {
        var result = Engine.Parse(formula, ParseOpts);
        var errors = new JsonArray(result.Errors.Select(e => (JsonNode)JsonValue.Create(e.Message)!).ToArray());
        return new JsonObject { ["ok"] = result.IsSuccess, ["errors"] = errors, ["ast"] = Ast(result.Root) };
    }

    public static JsonObject Eval(string formula, JsonObject? vars)
    {
        var cfg = new PowerFxConfig();
        cfg.EnableRegExFunctions();
        var engine = new RecalcEngine(cfg);
        if (vars != null)
            foreach (var (name, v) in vars)
                engine.UpdateVariable(name, ToFx(v));
        try
        {
            var r = engine.Eval(formula);
            if (r is ErrorValue ev)
                return new JsonObject { ["ok"] = true, ["error_value"] = string.Join("; ", ev.Errors.Select(e => e.Kind + ":" + e.Message)) };
            return new JsonObject { ["ok"] = true, ["value"] = FromFx(r), ["type"] = r.Type.ToString() };
        }
        catch (Exception ex)
        {
            return new JsonObject { ["ok"] = false, ["error"] = ex.Message };
        }
    }

    private static Engine Engine { get; } = new RecalcEngine(new PowerFxConfig());

    private static FormulaValue ToFx(JsonNode? v)
    {
        switch (v)
        {
            case null: return FormulaValue.NewBlank();
            case JsonValue jv when jv.TryGetValue<bool>(out var b): return FormulaValue.New(b);
            case JsonValue jv when jv.TryGetValue<string>(out var s): return FormulaValue.New(s);
            case JsonValue jv: return FormulaValue.New(jv.GetValue<decimal>());
            case JsonObject o when o["$date"] is JsonNode d:
                return FormulaValue.NewDateOnly(DateTime.ParseExact((string)d!, "yyyy-MM-dd", CultureInfo.InvariantCulture));
            case JsonObject o when o.ContainsKey("$blank"):
                return FormulaValue.NewBlank(BlankType(o["$blank"]?.GetValue<string>()));
            case JsonObject o:
                return FormulaValue.NewRecordFromFields(o.Select(kv => new NamedValue(kv.Key, ToFx(kv.Value))));
            case JsonArray a:
                var rows = a.Select(x => (RecordValue)ToFx(x)).ToArray();
                if (rows.Length == 0) return FormulaValue.NewTable(RecordType.Empty());
                return FormulaValue.NewTable(rows[0].Type, rows);
            default: throw new ArgumentException("unsupported value");
        }
    }

    private static FormulaType BlankType(string? t) => t switch
    {
        "number" => FormulaType.Decimal,
        "string" => FormulaType.String,
        "bool" => FormulaType.Boolean,
        "date" => FormulaType.Date,
        _ => FormulaType.Blank,
    };

    private static JsonNode? FromFx(FormulaValue v) => v switch
    {
        BlankValue => null,
        DecimalValue d => JsonValue.Create(d.Value),
        NumberValue n => JsonValue.Create((decimal)n.Value),
        StringValue s => JsonValue.Create(s.Value),
        BooleanValue b => JsonValue.Create(b.Value),
        DateValue dv => new JsonObject { ["$date"] = dv.GetConvertedValue(TimeZoneInfo.Utc).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) },
        DateTimeValue dt => new JsonObject { ["$datetime"] = dt.GetConvertedValue(TimeZoneInfo.Utc).ToString("o", CultureInfo.InvariantCulture) },
        RecordValue r => new JsonObject(r.Fields.Select(f => new KeyValuePair<string, JsonNode?>(f.Name, FromFx(f.Value)))),
        TableValue t => new JsonArray(t.Rows.Select(row => FromFx(row.Value)).ToArray()),
        _ => JsonValue.Create(v.ToObject()?.ToString()),
    };

    private static JsonObject Ast(TexlNode node)
    {
        var o = new JsonObject { ["k"] = node.Kind.ToString(), ["s"] = node.GetCompleteSpan().Min, ["e"] = node.GetCompleteSpan().Lim };
        switch (node)
        {
            case CallNode c:
                o["fn"] = c.Head.Namespace.Length == 0 ? c.Head.Name.Value : c.Head.Namespace.ToDottedSyntax() + "." + c.Head.Name.Value;
                o["args"] = Kids(c.Args.ChildNodes);
                break;
            case BinaryOpNode b:
                o["op"] = b.Op.ToString(); o["l"] = Ast(b.Left); o["r"] = Ast(b.Right); break;
            case UnaryOpNode u:
                o["op"] = u.Op.ToString(); o["x"] = Ast(u.Child); break;
            case VariadicOpNode vn:
                o["op"] = vn.Op.ToString(); o["args"] = Kids(vn.ChildNodes); break;
            case FirstNameNode f:
                o["name"] = f.Ident.Name.Value; break;
            case DottedNameNode dn:
                o["l"] = Ast(dn.Left); o["name"] = dn.Right.Name.Value; break;
            case NumLitNode n:
                o["v"] = n.ActualNumValue; break;
            case DecLitNode dl:
                o["v"] = dl.ActualDecValue; break;
            case StrLitNode s:
                o["v"] = s.Value; break;
            case BoolLitNode bl:
                o["v"] = bl.Value; break;
            case RecordNode r:
                var fields = new JsonObject();
                for (var i = 0; i < r.Ids.Count; i++) fields[r.Ids[i].Name.Value] = Ast(r.ChildNodes[i]);
                o["fields"] = fields; break;
            case TableNode t:
                o["args"] = Kids(t.ChildNodes); break;
            case StrInterpNode si:
                o["args"] = Kids(si.ChildNodes); break;
            case AsNode a:
                o["l"] = Ast(a.Left); o["name"] = a.Right.Name.Value; break;
        }
        return o;
    }

    private static JsonArray Kids(IEnumerable<TexlNode> nodes) => new(nodes.Select(n => (JsonNode)Ast(n)).ToArray());
}
