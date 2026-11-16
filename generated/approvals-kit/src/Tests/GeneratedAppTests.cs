// Generic tests that hold for every generated app. They exercise generated metadata
// (App.g.cs) through the real HTTP host; behavioural parity per rule lives in parity/.
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Factory.Generated;
using Factory.Runtime;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace Factory.Tests;

public sealed class HostFactory : WebApplicationFactory<Program>
{
    private readonly string _data = Path.Combine(Path.GetTempPath(), "factory-tests-" + Guid.NewGuid().ToString("N"));

    protected override void ConfigureWebHost(Microsoft.AspNetCore.Hosting.IWebHostBuilder builder)
    {
        builder.UseSetting("Identity:Mode", "demo");
        builder.UseSetting("Store:Kind", "file");
        builder.UseSetting("Store:Path", _data);
        builder.UseSetting("Seed:Path", Path.Combine(AppContext.BaseDirectory, "seed.json"));
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (Directory.Exists(_data)) Directory.Delete(_data, recursive: true);
    }
}

public sealed class GeneratedAppTests(HostFactory host) : IClassFixture<HostFactory>
{
    private static HttpRequestMessage Post(string path, string? user, object body)
    {
        var req = new HttpRequestMessage(HttpMethod.Post, path) { Content = JsonContent.Create(body) };
        if (user is not null) req.Headers.Add("X-Demo-User", user);
        return req;
    }

    [Fact]
    public void Every_formula_evaluates_on_a_blank_environment_without_crashing()
    {
        var ev = Evaluator.Run(App.Formulas, new Env(new Dictionary<string, object?>()));
        Assert.Equal(App.Formulas.Length, ev.Values.Count);
    }

    [Fact]
    public void Every_formula_input_is_either_a_control_property_or_a_known_global()
    {
        var outputs = App.Formulas.Select(f => f.Output).ToHashSet();
        foreach (var f in App.Formulas)
            foreach (var i in f.Inputs)
                Assert.True(i.Contains('.', StringComparison.Ordinal) || outputs.Contains(i) || App.Globals.Any(g => g.Name == i) || i.StartsWith("User()", StringComparison.Ordinal),
                    $"{f.Output} reads unknown input {i}");
    }

    [Fact]
    public void Formulas_are_in_dependency_order()
    {
        var seen = new HashSet<string>();
        foreach (var f in App.Formulas)
        {
            foreach (var i in f.Inputs.Where(i => App.Formulas.Any(g => g.Output == i && g.Output != f.Output)))
                Assert.Contains(i, seen);
            seen.Add(f.Output);
        }
    }

    [Fact]
    public void Every_action_targets_a_generated_container()
    {
        foreach (var a in App.Actions)
            Assert.Contains(App.Containers, c => c.Table == a.Table);
    }

    [Fact]
    public async Task Health_and_correlation_id_round_trip()
    {
        using var client = host.CreateClient();
        using var req = new HttpRequestMessage(HttpMethod.Get, "/health");
        req.Headers.Add("X-Correlation-ID", "test-correlation-123");
        using var res = await client.SendAsync(req);
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        Assert.Equal("test-correlation-123", res.Headers.GetValues("X-Correlation-ID").Single());
    }

    [Fact]
    public async Task Unknown_user_is_unauthorised()
    {
        using var client = host.CreateClient();
        foreach (var c in App.Containers)
        {
            using var res = await client.GetAsync($"/api/{c.EntitySet}");
            Assert.Equal(HttpStatusCode.Unauthorized, res.StatusCode);
        }
    }

    [Fact]
    public async Task Every_action_is_refused_for_every_seeded_role_without_the_privilege()
    {
        using var client = host.CreateClient();
        var users = await client.GetFromJsonAsync<JsonArray>("/api/demo/users") ?? [];
        var checkedAny = false;
        foreach (var a in App.Actions)
            foreach (var u in users)
            {
                var role = u!["role"]!.GetValue<string>();
                var granted = App.Roles.TryGetValue(role, out var t) && t.TryGetValue(a.Table, out var p) && p.ContainsKey(a.Operation);
                if (granted) continue;
                using var res = await client.SendAsync(Post($"/api/screens/{a.Screen}/actions/{a.Control}", u["email"]!.GetValue<string>(), new { inputs = new { } }));
                Assert.Equal(HttpStatusCode.Forbidden, res.StatusCode);
                checkedAny = true;
            }
        Assert.True(checkedAny || App.Actions.Length == 0, "no role/action pair lacked a privilege; refusal path untested");
    }

    [Fact]
    public async Task Guarded_create_with_blank_inputs_is_never_persisted()
    {
        using var client = host.CreateClient();
        var users = await client.GetFromJsonAsync<JsonArray>("/api/demo/users") ?? [];
        foreach (var a in App.Actions.Where(x => x.Guard is not null && x.Operation == "Create"))
        {
            var u = users.FirstOrDefault(x => App.Roles.TryGetValue(x!["role"]!.GetValue<string>(), out var t) && t.TryGetValue(a.Table, out var p) && p.ContainsKey(a.Operation));
            if (u is null) continue;
            using var res = await client.SendAsync(Post($"/api/screens/{a.Screen}/actions/{a.Control}", u["email"]!.GetValue<string>(), new { inputs = new { } }));
            // Refused by the legacy guard (409) or, where the legacy guard lets blanks through,
            // by the Dataverse required-column check (400). Never 200.
            Assert.Contains(res.StatusCode, new[] { HttpStatusCode.Conflict, HttpStatusCode.BadRequest });
        }
    }

    [Fact]
    public async Task Rows_are_only_written_through_guarded_legacy_actions()
    {
        // A generic create route would let a caller skip the DisplayMode guard on the button.
        using var client = host.CreateClient();
        var users = await client.GetFromJsonAsync<JsonArray>("/api/demo/users") ?? [];
        foreach (var c in App.Containers)
            foreach (var u in users)
            {
                using var res = await client.SendAsync(Post($"/api/{c.EntitySet}", u!["email"]!.GetValue<string>(), new { }));
                Assert.Equal(HttpStatusCode.MethodNotAllowed, res.StatusCode);
            }
    }

    [Fact]
    public void Outside_demo_mode_the_demo_header_is_ignored()
    {
        var dir = new UserDirectory(new Microsoft.Extensions.Configuration.ConfigurationBuilder().Build());
        var role = App.Roles.Keys.Order(StringComparer.Ordinal).FirstOrDefault() ?? "none";
        dir.Users.Add(new DemoUser("seeded@example.test", role, "bu"));
        var http = new Microsoft.AspNetCore.Http.DefaultHttpContext();
        http.Request.Headers["X-Demo-User"] = "seeded@example.test";
        Assert.False(dir.Demo);
        Assert.Null(dir.Resolve(http));
    }

    [Fact]
    public void Entra_principal_maps_its_app_role_to_a_legacy_role()
    {
        static string Principal(params (string Typ, string Val)[] claims) => Convert.ToBase64String(
            System.Text.Encoding.UTF8.GetBytes(new JsonObject
            {
                ["auth_typ"] = "aad",
                ["claims"] = new JsonArray(claims.Select(c => (JsonNode)new JsonObject { ["typ"] = c.Typ, ["val"] = c.Val }).ToArray()),
            }.ToJsonString()));
        foreach (var role in App.Roles.Keys)
        {
            var u = UserDirectory.FromPrincipal(Principal(("preferred_username", "a@example.test"), ("roles", role)));
            Assert.Equal(role, u?.Role);
        }
        Assert.Null(UserDirectory.FromPrincipal(Principal(("preferred_username", "a@example.test"), ("roles", "NotALegacyRole"))));
        Assert.Null(UserDirectory.FromPrincipal(Principal(("roles", App.Roles.Keys.FirstOrDefault() ?? "x"))));
        Assert.Null(UserDirectory.FromPrincipal("not base64!"));
    }
}
