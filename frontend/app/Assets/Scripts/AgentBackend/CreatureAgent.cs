using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

public static class CreatureAgent
{
    private const string BackendUrl = "https://your-api-endpoint.com/think";

    public static async Task<string> PostAsync(string jsonBody)
    {
        using var request = new UnityWebRequest(BackendUrl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonBody);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");

        var operation = request.SendWebRequest();
        while (!operation.isDone)
            await Task.Yield();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[CreatureAgent] {request.error}");
            return null;
        }

        return request.downloadHandler.text;
    }
}