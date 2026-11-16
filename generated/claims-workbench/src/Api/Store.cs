// Document persistence. Cosmos DB in Azure; a file-backed store with the same partition-key
// contract for the offline demo (no emulator dependency). Hand-written once per factory.
using System.Collections.Concurrent;
using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;
using Factory.Runtime;
using Microsoft.Azure.Cosmos;

namespace Factory.Api;

public interface IDocumentStore
{
    Task<JsonObject?> GetAsync(ContainerDef c, string id, CancellationToken ct);
    Task<IReadOnlyList<JsonObject>> ListAsync(ContainerDef c, CancellationToken ct);
    Task<JsonObject> CreateAsync(ContainerDef c, JsonObject doc, CancellationToken ct);
    Task<JsonObject> ReplaceAsync(ContainerDef c, JsonObject doc, CancellationToken ct);
}

public sealed class StoreError(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}

internal static class Docs
{
    public static string PartitionValue(ContainerDef c, JsonObject doc)
    {
        var field = c.PartitionKey.TrimStart('/');
        var v = doc[field]?.ToString();
        if (string.IsNullOrEmpty(v))
            throw new StoreError(400, $"{c.Table}: partition key {c.PartitionKey} is required");
        return v;
    }
}

/// <summary>One JSON file per container. Enforces the Cosmos rules the API relies on:
/// unique id, mandatory partition key, partition key immutable on replace.</summary>
public sealed class FileDocumentStore : IDocumentStore
{
    private readonly string _dir;
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();
    private static readonly JsonSerializerOptions Indented = new() { WriteIndented = true };

    public FileDocumentStore(string dir)
    {
        _dir = dir;
        Directory.CreateDirectory(dir);
    }

    private string PathOf(ContainerDef c) => Path.Combine(_dir, c.Container + ".json");

    private async Task<Dictionary<string, JsonObject>> LoadAsync(ContainerDef c, CancellationToken ct)
    {
        var p = PathOf(c);
        if (!File.Exists(p)) return new();
        await using var s = File.OpenRead(p);
        var arr = await JsonSerializer.DeserializeAsync<List<JsonObject>>(s, cancellationToken: ct) ?? new();
        return arr.ToDictionary(d => d["id"]!.ToString());
    }

    private async Task SaveAsync(ContainerDef c, Dictionary<string, JsonObject> rows, CancellationToken ct)
    {
        var tmp = PathOf(c) + ".tmp";
        await File.WriteAllTextAsync(tmp, JsonSerializer.Serialize(rows.Values.OrderBy(r => r["id"]!.ToString()), Indented), ct);
        File.Move(tmp, PathOf(c), overwrite: true);
    }

    private async Task<T> Locked<T>(ContainerDef c, Func<Task<T>> f, CancellationToken ct)
    {
        var l = _locks.GetOrAdd(c.Container, _ => new SemaphoreSlim(1, 1));
        await l.WaitAsync(ct);
        try { return await f(); } finally { l.Release(); }
    }

    public Task<JsonObject?> GetAsync(ContainerDef c, string id, CancellationToken ct) =>
        Locked(c, async () => (await LoadAsync(c, ct)).GetValueOrDefault(id), ct);

    public Task<IReadOnlyList<JsonObject>> ListAsync(ContainerDef c, CancellationToken ct) =>
        Locked<IReadOnlyList<JsonObject>>(c, async () => (await LoadAsync(c, ct)).Values.ToList(), ct);

    public Task<JsonObject> CreateAsync(ContainerDef c, JsonObject doc, CancellationToken ct) =>
        Locked(c, async () =>
        {
            Docs.PartitionValue(c, doc);
            var rows = await LoadAsync(c, ct);
            var id = doc["id"]!.ToString();
            if (rows.ContainsKey(id)) throw new StoreError(409, $"{c.Table}: id {id} exists");
            rows[id] = doc;
            await SaveAsync(c, rows, ct);
            return doc;
        }, ct);

    public Task<JsonObject> ReplaceAsync(ContainerDef c, JsonObject doc, CancellationToken ct) =>
        Locked(c, async () =>
        {
            var rows = await LoadAsync(c, ct);
            var id = doc["id"]!.ToString();
            if (!rows.TryGetValue(id, out var old)) throw new StoreError(404, $"{c.Table}: {id} not found");
            if (Docs.PartitionValue(c, old) != Docs.PartitionValue(c, doc))
                throw new StoreError(400, $"{c.Table}: partition key {c.PartitionKey} cannot change");
            rows[id] = doc;
            await SaveAsync(c, rows, ct);
            return doc;
        }, ct);
}

/// <summary>Azure Cosmos DB for NoSQL. Auth via managed identity (DefaultAzureCredential)
/// in Azure, or an emulator key locally. Point reads need the partition key, so GetAsync
/// falls back to a single-container query when only the id is known.</summary>
public sealed class CosmosDocumentStore(CosmosClient client, string database) : IDocumentStore
{
    private Container C(ContainerDef c) => client.GetContainer(database, c.Container);

    /// <summary>Emulator only: create the database and containers. In Azure they are
    /// declared in Bicep and the API identity has data-plane rights only.</summary>
    public async Task EnsureAsync(IEnumerable<ContainerDef> containers, CancellationToken ct)
    {
        var db = (await client.CreateDatabaseIfNotExistsAsync(database, cancellationToken: ct)).Database;
        foreach (var c in containers)
            await db.CreateContainerIfNotExistsAsync(new ContainerProperties(c.Container, c.PartitionKey), cancellationToken: ct);
    }

    public async Task<JsonObject?> GetAsync(ContainerDef c, string id, CancellationToken ct)
    {
        var q = new QueryDefinition("SELECT * FROM c WHERE c.id = @id").WithParameter("@id", id);
        var rows = await Query(C(c), q, ct);
        return rows.FirstOrDefault();
    }

    public async Task<IReadOnlyList<JsonObject>> ListAsync(ContainerDef c, CancellationToken ct) =>
        await Query(C(c), new QueryDefinition("SELECT * FROM c"), ct);

    private static async Task<List<JsonObject>> Query(Container container, QueryDefinition q, CancellationToken ct)
    {
        var outp = new List<JsonObject>();
        using var it = container.GetItemQueryStreamIterator(q);
        while (it.HasMoreResults)
        {
            using var resp = await it.ReadNextAsync(ct);
            resp.EnsureSuccessStatusCode();
            var page = await JsonNode.ParseAsync(resp.Content, cancellationToken: ct);
            foreach (var d in page?["Documents"]?.AsArray() ?? new JsonArray())
                if (d is JsonObject o) outp.Add(o.DeepClone().AsObject());
        }
        return outp;
    }

    public async Task<JsonObject> CreateAsync(ContainerDef c, JsonObject doc, CancellationToken ct)
    {
        var pk = new PartitionKey(Docs.PartitionValue(c, doc));
        using var body = new MemoryStream(JsonSerializer.SerializeToUtf8Bytes(doc));
        using var resp = await C(c).CreateItemStreamAsync(body, pk, cancellationToken: ct);
        if (resp.StatusCode == HttpStatusCode.Conflict) throw new StoreError(409, $"{c.Table}: id exists");
        resp.EnsureSuccessStatusCode();
        return doc;
    }

    public async Task<JsonObject> ReplaceAsync(ContainerDef c, JsonObject doc, CancellationToken ct)
    {
        var pk = new PartitionKey(Docs.PartitionValue(c, doc));
        using var body = new MemoryStream(JsonSerializer.SerializeToUtf8Bytes(doc));
        using var resp = await C(c).ReplaceItemStreamAsync(body, doc["id"]!.ToString(), pk, cancellationToken: ct);
        if (resp.StatusCode == HttpStatusCode.NotFound) throw new StoreError(404, $"{c.Table}: not found");
        resp.EnsureSuccessStatusCode();
        return doc;
    }
}
