using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

const int port = 8765;
Console.Title = "Gesture Remote";
Console.WriteLine("Gesture Remote가 실행 중입니다.");
Console.WriteLine($"iPhone 앱에 입력할 주소: {GetLocalIPv4()}");
Console.WriteLine($"포트: {port}");
Console.WriteLine("종료하려면 Ctrl+C를 누르세요.\n");

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{port}");
var app = builder.Build();
app.UseWebSockets();
app.Map("/ws", async context =>
{
    if (!context.WebSockets.IsWebSocketRequest)
    {
        context.Response.StatusCode = StatusCodes.Status400BadRequest;
        return;
    }

    using var socket = await context.WebSockets.AcceptWebSocketAsync();
    await HandleClientAsync(socket, context.Connection.RemoteIpAddress?.ToString() ?? "unknown");
});
await app.RunAsync();

static async Task HandleClientAsync(WebSocket socket, string remoteAddress)
{
    try
    {
        Console.WriteLine($"연결됨: {remoteAddress}");
        var buffer = new byte[4096];

        while (socket.State == WebSocketState.Open)
        {
            var result = await socket.ReceiveAsync(buffer, CancellationToken.None);
            if (result.MessageType == WebSocketMessageType.Close) break;
            var json = Encoding.UTF8.GetString(buffer, 0, result.Count);
            var message = JsonSerializer.Deserialize<RemoteMessage>(json);
            if (message?.Command is null) continue;

            InputController.Execute(message.Command, message.Value);
            Console.WriteLine($"{DateTime.Now:HH:mm:ss}  {message.Command} {message.Value}");

            var reply = Encoding.UTF8.GetBytes("""{"ok":true}""");
            await socket.SendAsync(reply, WebSocketMessageType.Text, true, CancellationToken.None);
        }
    }
    catch (Exception ex)
    {
        Console.WriteLine($"연결 종료: {ex.Message}");
    }
    finally
    {
        if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
            await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "closed", CancellationToken.None);
    }
}

static string GetLocalIPv4()
{
    var candidates = new List<IPAddress>();
    foreach (var network in NetworkInterface.GetAllNetworkInterfaces())
    {
        if (network.OperationalStatus != OperationalStatus.Up ||
            network.NetworkInterfaceType is NetworkInterfaceType.Loopback or NetworkInterfaceType.Tunnel)
            continue;

        foreach (var address in network.GetIPProperties().UnicastAddresses)
        {
            if (address.Address.AddressFamily == AddressFamily.InterNetwork &&
                !IPAddress.IsLoopback(address.Address))
                candidates.Add(address.Address);
        }
    }

    var privateAddress = candidates.FirstOrDefault(IsPrivateIPv4);
    return (privateAddress ?? candidates.FirstOrDefault())?.ToString() ?? "IP 주소를 찾지 못했습니다";
}

static bool IsPrivateIPv4(IPAddress address)
{
    var bytes = address.GetAddressBytes();
    return bytes[0] == 10 ||
           (bytes[0] == 172 && bytes[1] is >= 16 and <= 31) ||
           (bytes[0] == 192 && bytes[1] == 168);
}

sealed record RemoteMessage(string? Command, double Value = 0);

static class InputController
{
    private const uint KeyUp = 0x0002;
    private const uint MouseWheel = 0x0800;

    private const byte Left = 0x25;
    private const byte Up = 0x26;
    private const byte Right = 0x27;
    private const byte Down = 0x28;
    private const byte Space = 0x20;
    private const byte Control = 0x11;
    private const byte Add = 0x6B;
    private const byte Subtract = 0x6D;
    private const byte VolumeUp = 0xAF;
    private const byte VolumeDown = 0xAE;
    private const byte VolumeMute = 0xAD;
    private const byte MediaPlayPause = 0xB3;

    public static void Execute(string command, double value)
    {
        switch (command)
        {
            case "next": Tap(Right); break;
            case "previous": Tap(Left); break;
            case "up": Tap(Up); break;
            case "down": Tap(Down); break;
            case "scroll": mouse_event(MouseWheel, 0, 0, (uint)(int)(value * 120), 0); break;
            case "zoomIn": Chord(Control, Add); break;
            case "zoomOut": Chord(Control, Subtract); break;
            case "volumeUp": Tap(VolumeUp); break;
            case "volumeDown": Tap(VolumeDown); break;
            case "mute": Tap(VolumeMute); break;
            case "playPause": Tap(MediaPlayPause); break;
            case "space": Tap(Space); break;
        }
    }

    private static void Tap(byte key)
    {
        keybd_event(key, 0, 0, UIntPtr.Zero);
        keybd_event(key, 0, KeyUp, UIntPtr.Zero);
    }

    private static void Chord(byte modifier, byte key)
    {
        keybd_event(modifier, 0, 0, UIntPtr.Zero);
        Tap(key);
        keybd_event(modifier, 0, KeyUp, UIntPtr.Zero);
    }

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extraInfo);

    [DllImport("user32.dll")]
    private static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
