// Generic API host for a generated app. Hand-written once per factory; every app-specific
// fact (formulas, actions, containers, roles) comes from the generated App.g.cs.
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Factory.Api;
using Factory.Generated;
using Factory.Runtime;
using Microsoft.Azure.Cosmos;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.Logging.AddJsonConsole(o =>
{
    o.IncludeScopes = true;
    o.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ";
    o.UseUtcTimestamp = true;
});
builder.Services.AddSingleton<IDocumentStore>(sp =>
{
    var cfg = sp.GetRequiredService<IConfiguration>();
    return cfg["Store:Kind"] switch
    {
        "cosmos" => new CosmosDocumentStore(CosmosFactory.Client(cfg), cfg["Store:Database"] ?? App.Id),
        _ => new FileDocumentStore(cfg["Store:Path"] ?? Path.Combine(AppContext.BaseDirectory, "data")),
    };
});
builder.Services.AddSingleton<UserDirectory>();
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod()
    .WithExposedHeaders(Correlation.Header)));
var app = builder.Build();
app.UseCors();
app.Use(Correlation.Middleware);

if (app.Services.GetRequiredService<IDocumentStore>() is CosmosDocumentStore cosmos && app.Configuration.GetValue<bool>("Store:Emulator"))
    await cosmos.EnsureAsync(App.Containers, default);
await Seeding.RunAsync(app.Services, app.Configuration["Seed:Path"], app.Logger);

app.MapGet("/openapi.json", () => Results.File(Path.Combine(AppContext.BaseDirectory, "openapi.json"), "application/json"));

app.MapGet("/health", () => Results.Ok(new { status = "ok", app = App.Id }));

app.MapGet("/api/demo/users", (UserDirectory d) =>
    d.Demo ? Results.Ok(d.Users.Select(u => new { u.Email, u.Role, u.BusinessUnit })) : Results.NotFound());

foreach (var c in App.Containers)
{
    app.MapGet($"/api/{c.EntitySet}", async (HttpContext http, IDocumentStore store, UserDirectory dir, CancellationToken ct) =>
    {
        var user = dir.Resolve(http);
        if (user is null) return Results.Unauthorized();
        var depth = Rbac.Depth(user.Role, c.Table, "Read");
        if (depth is null) return Results.Problem(Rbac.Denied(user, c.Table, "Read"), statusCode: 403);
        var rows = await store.ListAsync(c, ct);
        return Results.Ok(rows.Where(r => Rbac.InScope(depth, user, r)).OrderBy(r => r["id"]!.ToString()));
    });
    app.MapGet($"/api/{c.EntitySet}/{{id}}", async (string id, HttpContext http, IDocumentStore store, UserDirectory dir, CancellationToken ct) =>
    {
        var user = dir.Resolve(http);
        if (user is null) return Results.Unauthorized();
        var depth = Rbac.Depth(user.Role, c.Table, "Read");
        if (depth is null) return Results.Problem(Rbac.Denied(user, c.Table, "Read"), statusCode: 403);
        var row = await store.GetAsync(c, id, ct);
        return row is not null && Rbac.InScope(depth, user, row) ? Results.Ok(row) : Results.NotFound();
    });
}

app.MapPost("/api/screens/{screen}/evaluate", async (string screen, EvaluateRequest req, HttpContext http, IDocumentStore store, UserDirectory dir, CancellationToken ct) =>
{
    var user = dir.Resolve(http);
    if (user is null) return Results.Unauthorized();
    if (!App.Formulas.Any(f => f.Screen == screen) && !App.Actions.Any(a => a.Screen == screen)) return Results.NotFound();
    var env = await Session.EnvAsync(req.Inputs, user, store, ct);
    var ev = Evaluator.Run(App.Formulas, env);
    // Canvas formulas reference controls on other screens, so the whole app is evaluated
    // and the response carries every computed value; `screen` lists the ones it owns.
    return Results.Ok(new
    {
        values = ev.Values,
        errors = ev.Errors,
        screen = App.Formulas.Where(f => f.Screen == screen).Select(f => f.Output),
    });
});

app.MapPost("/api/rules/{ruleId}/evaluate", async (string ruleId, EvaluateRequest req, HttpContext http, IDocumentStore store, UserDirectory dir, CancellationToken ct) =>
{
    var user = dir.Resolve(http);
    if (user is null) return Results.Unauthorized();
    var mine = App.Formulas.Where(f => f.RuleId == ruleId).ToList();
    if (mine.Count == 0) return Results.NotFound();
    var env = await Session.EnvAsync(req.Inputs, user, store, ct);
    var ev = Evaluator.Run(App.Formulas, env);
    return Results.Ok(new
    {
        rule = ruleId,
        values = mine.ToDictionary(f => f.Output, f => ev.Values[f.Output]),
        sources = mine.Select(f => f.Source),
        errors = ev.Errors.Where(e => mine.Any(f => f.Output == e.Key)).ToDictionary(),
    });
});

app.MapPost("/api/screens/{screen}/actions/{control}", async (string screen, string control, ActionRequest req, HttpContext http, IDocumentStore store, UserDirectory dir, ILogger<Program> log, CancellationToken ct) =>
{
    var user = dir.Resolve(http);
    if (user is null) return Results.Unauthorized();
    var action = App.Actions.FirstOrDefault(a => a.Screen == screen && a.Control == control);
    if (action is null) return Results.NotFound();
    var c = App.Containers.First(x => x.Table == action.Table);
    var depth = Rbac.Depth(user.Role, action.Table, action.Operation);
    if (depth is null)
    {
        log.LogWarning("Refused {Screen}/{Control}: {Role} lacks {Operation} on {Table}", screen, control, user.Role, action.Operation, action.Table);
        return Results.Problem(Rbac.Denied(user, action.Table, action.Operation), statusCode: 403);
    }
    var env = await Session.EnvAsync(req.Inputs, user, store, ct);
    var ev = Evaluator.Run(App.Formulas, env);
    var used = Evaluator.DependsOn(App.Formulas, action.Fields.SelectMany(f => f.Inputs).Concat(action.Guard is null ? [] : [action.Guard]));
    var blocking = ev.Errors.Where(e => used.Contains(e.Key)).ToDictionary();
    if (blocking.Count > 0)
    {
        log.LogWarning("Refused {Screen}/{Control}: {Count} formula errors", screen, control, blocking.Count);
        return Results.Problem("Legacy formulas this action depends on raised errors; fix the inputs before acting.",
            statusCode: 422, extensions: new Dictionary<string, object?> { ["errors"] = blocking });
    }
    if (action.Guard is not null && !string.Equals(Env.ToText(env.Raw(action.Guard)), "Edit", StringComparison.Ordinal))
    {
        log.LogWarning("Refused {Screen}/{Control}: guard {Guard} = {Mode}", screen, control, action.Guard, env.Raw(action.Guard));
        return Results.Problem($"{action.Guard} is {env.Raw(action.Guard) ?? "blank"}; the legacy button is not enabled for this state.",
            statusCode: 409, extensions: new Dictionary<string, object?> { ["values"] = ev.Values, ["errors"] = ev.Errors });
    }
    var fields = new Dictionary<string, object?>();
    foreach (var f in action.Fields) fields[f.Column] = f.Eval(env);
    foreach (var k in action.ContextFields)
        if (req.Context?.TryGetValue(k, out var v) == true) fields[k] = Session.Plain(v);
    JsonObject doc;
    if (action.Operation == "Create")
    {
        doc = Records.New(c, user, fields);
        var missing = Records.Missing(c, doc);
        if (missing.Count > 0)
            return Results.ValidationProblem(missing.ToDictionary(m => m, m => new[] { "required" }));
        await store.CreateAsync(c, doc, ct);
    }
    else
    {
        if (req.RowId is null) return Results.ValidationProblem(new Dictionary<string, string[]> { [action.Row ?? "row"] = new[] { "required" } });
        var row = await store.GetAsync(c, req.RowId, ct);
        if (row is null || !Rbac.InScope(depth, user, row)) return Results.NotFound();
        doc = Records.Apply(row, fields);
        await store.ReplaceAsync(c, doc, ct);
    }
    log.LogInformation("Action {Screen}/{Control} {Operation} {Table} {Id} by {User} ({Role}); source {Source}",
        screen, control, action.Operation, action.Table, doc["id"], user.Email, user.Role, action.Source);
    return Results.Ok(new { record = doc, navigateTo = action.NavigatesTo });
});

app.Run();

public static class CosmosFactory
{
    /// <summary>Azure: endpoint + managed identity (local auth is disabled in Bicep).
    /// Local emulator: its well-known connection string over HTTP gateway mode.</summary>
    public static CosmosClient Client(IConfiguration cfg)
    {
        var emulator = cfg.GetValue<bool>("Store:Emulator");
        var opts = new CosmosClientOptions
        {
            ConnectionMode = emulator ? ConnectionMode.Gateway : ConnectionMode.Direct,
            LimitToEndpoint = emulator,
        };
        var endpoint = cfg["Store:CosmosEndpoint"];
        return string.IsNullOrEmpty(endpoint)
            ? new CosmosClient(cfg["Store:CosmosConnectionString"], opts)
            : new CosmosClient(endpoint, new Azure.Identity.DefaultAzureCredential(), opts);
    }
}

public sealed record EvaluateRequest(Dictionary<string, JsonElement>? Inputs);
public sealed record ActionRequest(Dictionary<string, JsonElement>? Inputs, Dictionary<string, JsonElement>? Context, string? RowId);

public sealed record DemoUser(string Email, string Role, string BusinessUnit);

/// <summary>Who is calling. Identity:Mode=demo (offline only) trusts X-Demo-User naming a
/// seeded user. Any other value, including unset, ignores that header and requires the principal
/// that Azure Container Apps built-in authentication injects as X-MS-CLIENT-PRINCIPAL after it
/// has validated the Entra ID token (the platform drops client-supplied copies of the header).
/// The Entra app role must name a legacy security role; the RBAC checks are unchanged.</summary>
public sealed class UserDirectory(IConfiguration cfg)
{
    public const string PrincipalHeader = "X-MS-CLIENT-PRINCIPAL";
    public bool Demo { get; } = string.Equals(cfg["Identity:Mode"], "demo", StringComparison.OrdinalIgnoreCase);
    public List<DemoUser> Users { get; } = new();

    public DemoUser? Resolve(HttpContext http) => Demo
        ? Users.FirstOrDefault(u => string.Equals(u.Email, http.Request.Headers["X-Demo-User"].ToString(), StringComparison.OrdinalIgnoreCase))
        : FromPrincipal(http.Request.Headers[PrincipalHeader].ToString());

    public static DemoUser? FromPrincipal(string header)
    {
        if (string.IsNullOrEmpty(header)) return null;
        JsonObject? p;
        try
        {
            p = JsonNode.Parse(Convert.FromBase64String(header)) as JsonObject;
        }
        catch (FormatException) { return null; }
        catch (JsonException) { return null; }
        if (p?["claims"] is not JsonArray arr) return null;
        var claims = arr.OfType<JsonObject>()
            .Select(c => (Typ: c["typ"]?.ToString() ?? "", Val: c["val"]?.ToString() ?? ""))
            .ToList();
        string? Claim(params string[] types) =>
            claims.Where(c => types.Contains(c.Typ) && c.Val.Length > 0).Select(c => c.Val).FirstOrDefault();
        var roleTyp = p["role_typ"]?.ToString() ?? "roles";
        var email = Claim("preferred_username", "email", "upn");
        var role = claims.Where(c => c.Typ == roleTyp || c.Typ == "roles").Select(c => c.Val)
            .Where(App.Roles.ContainsKey).Order(StringComparer.Ordinal).FirstOrDefault();
        return email is null || role is null ? null : new DemoUser(email, role, Claim("businessUnit") ?? "");
    }
}

public static class Correlation
{
    public const string Header = "X-Correlation-ID";

    public static async Task Middleware(HttpContext http, RequestDelegate next)
    {
        var id = http.Request.Headers[Header].FirstOrDefault();
        if (string.IsNullOrWhiteSpace(id) || id.Length > 64) id = Activity.Current?.TraceId.ToString() ?? Guid.NewGuid().ToString("N");
        http.Response.Headers[Header] = id;
        var log = http.RequestServices.GetRequiredService<ILogger<Program>>();
        using (log.BeginScope(new Dictionary<string, object> { ["CorrelationId"] = id, ["User"] = http.Request.Headers["X-Demo-User"].ToString() }))
        {
            var sw = Stopwatch.StartNew();
            await next(http);
            log.LogInformation("{Method} {Path} -> {Status} in {Ms} ms", http.Request.Method, http.Request.Path, http.Response.StatusCode, sw.ElapsedMilliseconds);
        }
    }
}

public static class Rbac
{
    /// <summary>Legacy Dataverse depth for (role, table, privilege), or null when not granted.</summary>
    public static string? Depth(string role, string table, string privilege) =>
        App.Roles.TryGetValue(role, out var t) && t.TryGetValue(table, out var p) && p.TryGetValue(privilege, out var d) ? d : null;

    public static bool InScope(string depth, DemoUser user, JsonObject row) => depth switch
    {
        "Global" or "Organization" => true,
        "BusinessUnit" or "Deep" => row["_businessUnit"]?.ToString() == user.BusinessUnit,
        _ => string.Equals(row["_owner"]?.ToString(), user.Email, StringComparison.OrdinalIgnoreCase),
    };

    public static string Denied(DemoUser u, string table, string privilege) =>
        $"Role {u.Role} has no {privilege} privilege on {table} in the legacy security model.";
}

public static class Records
{
    public static JsonObject New(ContainerDef c, DemoUser owner, IDictionary<string, object?> fields)
    {
        var doc = new JsonObject { ["id"] = Guid.NewGuid().ToString() };
        foreach (var (k, v) in fields)
            if (c.Fields.Any(f => f.Name == k)) doc[k] = ToNode(v);
        doc[c.IdField] = doc["id"]!.ToString();
        doc["_owner"] = owner.Email;
        doc["_businessUnit"] = owner.BusinessUnit;
        doc["_createdOn"] = DateTime.UtcNow.ToString("O");
        return doc;
    }

    public static JsonObject Apply(JsonObject row, IDictionary<string, object?> fields)
    {
        var doc = row.DeepClone().AsObject();
        foreach (var (k, v) in fields) doc[k] = ToNode(v);
        doc["_modifiedOn"] = DateTime.UtcNow.ToString("O");
        return doc;
    }

    public static List<string> Missing(ContainerDef c, JsonObject doc) =>
        c.Fields.Where(f => f.Required && f.Type != "primarykey" && (doc[f.Name] is null || doc[f.Name]!.ToString() == ""))
            .Select(f => f.Name).ToList();

    private static JsonNode? ToNode(object? v) => v switch
    {
        null => null,
        JsonNode n => n,
        DateTime d => JsonValue.Create(d.ToString("yyyy-MM-dd")),
        decimal m => JsonValue.Create(m),
        bool b => JsonValue.Create(b),
        _ => JsonValue.Create(v.ToString()),
    };
}

public static class Session
{
    /// <summary>Screen inputs from the client, plus App.OnStart globals the server resolves
    /// for the signed-in user. Globals are never accepted from the client.</summary>
    public static async Task<Env> EnvAsync(Dictionary<string, JsonElement>? inputs, DemoUser user, IDocumentStore store, CancellationToken ct)
    {
        var env = new Env();
        foreach (var (k, v) in inputs ?? new())
            if (!App.Globals.Any(g => string.Equals(g.Name, k, StringComparison.OrdinalIgnoreCase)) && !k.StartsWith("User().", StringComparison.Ordinal))
                env.Set(k, Plain(v));
        env.Set("User().Email", user.Email);
        foreach (var g in App.Globals)
        {
            object? value = null;
            if (g.Table is not null)
            {
                var c = App.Containers.First(x => x.Table == g.Table);
                var rows = await store.ListAsync(c, ct);
                var hit = rows.FirstOrDefault(r => string.Equals(r[g.MatchColumn!]?.ToString(), user.Email, StringComparison.OrdinalIgnoreCase));
                value = hit?[g.ValueColumn!] is JsonValue jv && jv.TryGetValue<decimal>(out var d) ? d : hit?[g.ValueColumn!]?.ToString();
            }
            env.Set(g.Name, value);
        }
        return env;
    }

    public static object? Plain(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.String => v.GetString(),
        JsonValueKind.Number => v.GetDecimal(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        _ => null,
    };
}

public static class Seeding
{
    /// <summary>Loads synthetic demo users and rows once into an empty store.</summary>
    public static async Task RunAsync(IServiceProvider sp, string? path, ILogger log)
    {
        if (string.IsNullOrEmpty(path) || !File.Exists(path)) return;
        var seed = JsonNode.Parse(await File.ReadAllTextAsync(path))!.AsObject();
        var dir = sp.GetRequiredService<UserDirectory>();
        foreach (var u in seed["users"]!.AsArray())
            dir.Users.Add(new DemoUser(u!["email"]!.ToString(), u["role"]!.ToString(), u["businessUnit"]!.ToString()));
        var store = sp.GetRequiredService<IDocumentStore>();
        foreach (var c in App.Containers)
        {
            if ((await store.ListAsync(c, default)).Count > 0) continue;
            foreach (var r in seed["rows"]?[c.Table]?.AsArray() ?? new JsonArray())
                await store.CreateAsync(c, r!.DeepClone().AsObject(), default);
        }
        log.LogInformation("Seeded {Users} demo users from {Path}", dir.Users.Count, path);
    }
}

public partial class Program;
