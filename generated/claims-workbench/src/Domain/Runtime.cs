// Evaluation runtime for generated rules. Hand-written once and shared by every generated
// app; the formula table it walks (Formulas.g.cs) is generated from the legacy AST.
using System.Globalization;

namespace Factory.Runtime;

/// <summary>A compiled legacy formula bound to its output reference (e.g. "lblFourEyes.Visible").</summary>
public sealed record Formula(
    string Output, string Screen, string? RuleId, string Source, string[] Inputs, Func<Env, object?> Eval);

/// <summary>A column value computed from screen state when a legacy button runs Patch.</summary>
public sealed record FieldDef(string Column, string[] Inputs, Func<Env, object?> Eval);

/// <summary>A legacy button action: guard formula, privilege, Patch target and fields.</summary>
public sealed record ActionDef(
    string Screen, string Control, string Table, string Operation, string? Guard, string? Row,
    FieldDef[] Fields, string[] ContextFields, string[] NavigatesTo, string Source);

public sealed record FieldMeta(string Name, string Type, bool Required, string? Pii);

public sealed record ContainerDef(
    string Table, string EntitySet, string Container, string IdField, string PartitionKey,
    FieldMeta[] Fields);

/// <summary>Screen state: control-property references to values, Power Fx coercions on read.</summary>
public sealed class Env
{
    private readonly Dictionary<string, object?> _v = new(StringComparer.OrdinalIgnoreCase);

    public Env(IReadOnlyDictionary<string, object?>? values = null)
    {
        if (values is null) return;
        foreach (var (k, v) in values) _v[k] = v;
    }

    public bool Has(string r) => _v.ContainsKey(r);
    public object? Raw(string r) => _v.TryGetValue(r, out var v) ? v : null;
    public void Set(string r, object? v) => _v[r] = v;
    public IReadOnlyDictionary<string, object?> Values => _v;

    public decimal? Num(string r) => Raw(r) switch
    {
        null => null,
        decimal d => d,
        int i => i,
        long l => l,
        double x => (decimal)x,
        bool b => b ? 1m : 0m,
        string s => Fx.Value(s),
        var o => throw new FxException($"{r}: cannot use {o.GetType().Name} as a number"),
    };

    public string? Str(string r) => ToText(Raw(r));

    public bool? Bool(string r) => Raw(r) switch
    {
        null => null,
        bool b => b,
        decimal d => d != 0m,
        string s when s.Length == 0 => null,
        string s when bool.TryParse(s, out var b) => b,
        var o => throw new FxException($"{r}: cannot use '{o}' as a boolean"),
    };

    public DateTime? Date(string r) => Raw(r) switch
    {
        null => null,
        DateTime d => d,
        string s when s.Length == 0 => null,
        string s => DateTime.Parse(s, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal),
        var o => throw new FxException($"{r}: cannot use '{o}' as a date"),
    };

    public static string? ToText(object? v) => v switch
    {
        null => null,
        string s => s,
        decimal d => Fx.Text(d),
        bool b => Fx.Text(b),
        DateTime d => d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
        var o => Convert.ToString(o, CultureInfo.InvariantCulture),
    };
}

public sealed record Evaluation(IReadOnlyDictionary<string, object?> Values, IReadOnlyDictionary<string, string> Errors);

public static class Evaluator
{
    /// <summary>Data property a control shows until the user changes it, keyed by default property.</summary>
    private static readonly Dictionary<string, string> DefaultOf = new()
    {
        ["DefaultDate"] = "SelectedDate",
        ["Default"] = "Text",
    };

    /// <summary>
    /// Evaluate every formula once, in the dependency order fixed at generation time. A formula
    /// that raises a Power Fx error yields blank plus an error entry, as the legacy app shows.
    /// </summary>
    public static Evaluation Run(IEnumerable<Formula> formulas, Env env)
    {
        var errors = new Dictionary<string, string>();
        var computed = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        foreach (var f in formulas)
        {
            object? value;
            try { value = Coerce(f.Output, f.Eval(env)); }
            catch (FxException e) { value = null; errors[f.Output] = e.Message; }
            env.Set(f.Output, value);
            computed[f.Output] = value;
            var dot = f.Output.LastIndexOf('.');
            if (DefaultOf.TryGetValue(f.Output[(dot + 1)..], out var data))
            {
                var target = f.Output[..dot] + "." + data;
                if (!env.Has(target) || env.Raw(target) is null) env.Set(target, value);
            }
        }
        return new Evaluation(computed, errors);
    }

    public static object? Coerce(string output, object? v)
    {
        var prop = output[(output.LastIndexOf('.') + 1)..];
        return prop switch
        {
            "Text" => Env.ToText(v),
            "Visible" => v is null ? false : new Env(new Dictionary<string, object?> { ["x"] = v }).Bool("x") ?? false,
            "DisplayMode" => v,
            _ => v,
        };
    }
}

/// <summary>An App.OnStart global. Per-user lookups are resolved on the server from the
/// signed-in identity; anything else is supplied as blank so dependent guards fail closed.</summary>
public sealed record GlobalDef(string Name, string? Table, string? MatchColumn, string? ValueColumn, string? Unresolved);
