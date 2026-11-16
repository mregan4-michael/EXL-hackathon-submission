// Parity runner: one JSON request per stdin line, one JSON result per stdout line.
//   in:  {"id":"..","output":"lblFourEyes.Visible","env":{"txtClaimAmount.Text":"10000", "d": {"$date":"2024-01-15"}}}
//   out: {"id":"..","value":true} | {"id":"..","error":"..","kind":"fx|crash|unknown"}
// It calls exactly the generated Formula.Eval the API uses; nothing here re-implements a rule.
using System.Globalization;
using System.Text.Json;
using Factory.Generated;
using Factory.Runtime;

var byOutput = App.Formulas.ToDictionary(f => f.Output, StringComparer.Ordinal);
using var stdout = Console.OpenStandardOutput();
string? line;
while ((line = Console.ReadLine()) is not null)
{
    if (line.Length == 0) continue;
    using var req = JsonDocument.Parse(line);
    var id = req.RootElement.GetProperty("id").GetString();
    var output = req.RootElement.GetProperty("output").GetString() ?? "";
    using var buf = new MemoryStream();
    using (var w = new Utf8JsonWriter(buf))
    {
        w.WriteStartObject();
        w.WriteString("id", id);
        if (!byOutput.TryGetValue(output, out var f))
        {
            w.WriteString("error", $"no generated formula for {output}");
            w.WriteString("kind", "unknown");
        }
        else
        {
            var env = new Env(Parity.ReadEnv(req.RootElement.GetProperty("env")));
            try
            {
                var v = f.Eval(env);
                w.WritePropertyName("value");
                Parity.Write(w, v);
            }
            catch (FxException e)
            {
                w.WriteString("error", e.Message);
                w.WriteString("kind", "fx");
            }
            catch (Exception e)
            {
                w.WriteString("error", $"{e.GetType().Name}: {e.Message}");
                w.WriteString("kind", "crash");
            }
        }
        w.WriteEndObject();
    }
    buf.WriteByte((byte)'\n');
    stdout.Write(buf.ToArray());
}

internal static class Parity
{
    public static Dictionary<string, object?> ReadEnv(JsonElement env)
    {
        var d = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        foreach (var p in env.EnumerateObject()) d[p.Name] = Read(p.Value);
        return d;
    }

    private static object? Read(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.Null => null,
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Number => v.GetDecimal(),
        JsonValueKind.String => v.GetString(),
        JsonValueKind.Object when v.TryGetProperty("$date", out var d) => DateTime.Parse(
            d.GetString() ?? "", CultureInfo.InvariantCulture,
            DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal),
        _ => throw new FormatException($"unsupported parity input {v.ValueKind}"),
    };

    public static void Write(Utf8JsonWriter w, object? v)
    {
        switch (v)
        {
            case null: w.WriteNullValue(); break;
            case bool b: w.WriteBooleanValue(b); break;
            case decimal m: w.WriteRawValue(m.ToString(CultureInfo.InvariantCulture)); break;
            case string s: w.WriteStringValue(s); break;
            case DateTime t:
                w.WriteStartObject();
                w.WriteString("$date", t.TimeOfDay == TimeSpan.Zero
                    ? t.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
                    : t.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture));
                w.WriteEndObject();
                break;
            default: w.WriteStringValue($"<{v.GetType().Name}>"); break;
        }
    }
}
