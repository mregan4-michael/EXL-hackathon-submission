// Power Fx semantics runtime for generated rules. Hand-written once and shared by
// every generated app; the rule bodies that call it are compiled from the legacy AST.
using System.Globalization;
using System.Text.RegularExpressions;

namespace Factory.Runtime;

public sealed class FxException(string message) : Exception(message);

public static class Fx
{
    public enum TimeUnit { Days, Months, Quarters, Years, Hours, Minutes, Seconds, Milliseconds }

    private static decimal N(decimal? x) => x ?? 0m;

    public static bool B(bool? b) => b ?? false;
    public static bool B(object? o) => o is bool b && b;

    public static decimal? Value(string? s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        var t = s.Trim();
        var pct = t.EndsWith('%');
        if (pct) t = t[..^1];
        if (decimal.TryParse(t, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture, out var v))
            return pct ? v / 100m : v;
        throw new FxException($"Value: '{s}' is not a number");
    }

    public static decimal? ToNum(bool? b) => b is null ? null : (b.Value ? 1m : 0m);

    public static string? Text(decimal? n) => n?.ToString(CultureInfo.InvariantCulture);
    public static string? Text(bool? b) => b is null ? null : (b.Value ? "true" : "false");
    public static string? Text(DateTime? d) => d?.ToString("M/d/yyyy", CultureInfo.InvariantCulture);

    // Arithmetic coerces blank to 0 even when both operands are blank (Blank() + Blank() = 0).
    public static decimal? Add(decimal? a, decimal? b) => N(a) + N(b);
    public static decimal? Mul(decimal? a, decimal? b) => N(a) * N(b);
    public static decimal? Div(decimal? a, decimal? b)
    {
        if (N(b) == 0m) throw new FxException("Div: division by zero");
        return N(a) / N(b);
    }
    public static decimal? Neg(decimal? a) => -N(a);
    public static decimal? Abs(decimal? a) => a is null ? null : Math.Abs(a.Value);

    public static bool? Gt(decimal? a, decimal? b) => N(a) > N(b);
    public static bool? Ge(decimal? a, decimal? b) => N(a) >= N(b);
    public static bool? Lt(decimal? a, decimal? b) => N(a) < N(b);
    public static bool? Le(decimal? a, decimal? b) => N(a) <= N(b);
    public static bool? Eq(decimal? a, decimal? b) => a == b;
    public static bool? Ne(decimal? a, decimal? b) => a != b;

    private static DateTime D(DateTime? d) => d ?? Epoch;
    public static bool? Gt(DateTime? a, DateTime? b) => D(a) > D(b);
    public static bool? Ge(DateTime? a, DateTime? b) => D(a) >= D(b);
    public static bool? Lt(DateTime? a, DateTime? b) => D(a) < D(b);
    public static bool? Le(DateTime? a, DateTime? b) => D(a) <= D(b);
    public static bool? Eq(DateTime? a, DateTime? b) => a == b;
    public static bool? Ne(DateTime? a, DateTime? b) => a != b;

    public static bool? Eq(string? a, string? b) => string.IsNullOrEmpty(a) && string.IsNullOrEmpty(b) || a == b;
    public static bool? Ne(string? a, string? b) => !B(Eq(a, b));
    public static bool? Eq(bool? a, bool? b) => a == b;
    public static bool? Ne(bool? a, bool? b) => a != b;

    public static bool IsBlank(object? v) => v is null || v is string s && s.Length == 0;

    public static decimal? Len(string? s) => (s ?? "").Length;
    public static bool? StartsWith(string? s, string? p) => (s ?? "").StartsWith(p ?? "", StringComparison.OrdinalIgnoreCase);
    public static bool? EndsWith(string? s, string? p) => (s ?? "").EndsWith(p ?? "", StringComparison.OrdinalIgnoreCase);
    public static bool? IsMatch(string? s, string pattern) =>
        Regex.IsMatch(s ?? "", "^(?:" + pattern + ")$", RegexOptions.None, TimeSpan.FromSeconds(1));
    public static string? Lower(string? s) => s?.ToLowerInvariant();
    public static string? Upper(string? s) => s?.ToUpperInvariant();
    public static string? Trim(string? s) => s is null ? null : Regex.Replace(s.Trim(), " {2,}", " ");
    public static string? Concat(string? a, string? b) => (a ?? "") + (b ?? "");

    public static decimal? Round(decimal? x, decimal? d) => x is null ? null : Math.Round(N(x), (int)N(d), MidpointRounding.AwayFromZero);
    public static decimal? RoundUp(decimal? x, decimal? d) => x is null ? null : Scale(N(x), (int)N(d), v => v < 0 ? Math.Floor(v) : Math.Ceiling(v));
    public static decimal? RoundDown(decimal? x, decimal? d) => x is null ? null : Scale(N(x), (int)N(d), Math.Truncate);
    private static decimal Scale(decimal v, int digits, Func<decimal, decimal> f)
    {
        var m = (decimal)Math.Pow(10, digits);
        return f(v * m) / m;
    }

    public static decimal? Max(params decimal?[] xs) => xs.Any(x => x is not null) ? xs.Where(x => x is not null).Max() : null;
    public static decimal? Min(params decimal?[] xs) => xs.Any(x => x is not null) ? xs.Where(x => x is not null).Min() : null;
    public static decimal? Sum(params decimal?[] xs) => xs.Any(x => x is not null) ? xs.Sum(x => N(x)) : null;

    // Power Fx coerces a blank date to its epoch (1899-12-30) in date arithmetic, not to blank.
    private static readonly DateTime Epoch = new(1899, 12, 30, 0, 0, 0, DateTimeKind.Utc);

    public static decimal? DateDiff(DateTime? a, DateTime? b, TimeUnit unit)
    {
        var (x, y) = (a ?? Epoch, b ?? Epoch);
        var months = (y.Year - x.Year) * 12 + y.Month - x.Month;
        return unit switch
        {
            TimeUnit.Days => (decimal)(y.Date - x.Date).TotalDays,
            TimeUnit.Months => months,
            TimeUnit.Quarters => (y.Year - x.Year) * 4 + (y.Month - 1) / 3 - (x.Month - 1) / 3,
            TimeUnit.Years => y.Year - x.Year,
            TimeUnit.Hours => (decimal)Math.Truncate((y - x).TotalHours),
            TimeUnit.Minutes => (decimal)Math.Truncate((y - x).TotalMinutes),
            TimeUnit.Seconds => (decimal)Math.Truncate((y - x).TotalSeconds),
            _ => (decimal)(y - x).TotalMilliseconds,
        };
    }

    public static DateTime? DateAdd(DateTime? d, decimal? n, TimeUnit unit)
    {
        var x = d ?? Epoch;
        var k = (int)Math.Truncate(N(n));
        return unit switch
        {
            // Fractional days move the time of day, so a date lands on the floor.
            TimeUnit.Days => x.AddDays((double)Math.Floor(N(n))),
            TimeUnit.Months => x.AddMonths(k),
            TimeUnit.Quarters => x.AddMonths(3 * k),
            TimeUnit.Years => x.AddYears(k),
            TimeUnit.Hours => x.AddHours(k),
            TimeUnit.Minutes => x.AddMinutes(k),
            TimeUnit.Seconds => x.AddSeconds(k),
            _ => x.AddMilliseconds(k),
        };
    }
}
