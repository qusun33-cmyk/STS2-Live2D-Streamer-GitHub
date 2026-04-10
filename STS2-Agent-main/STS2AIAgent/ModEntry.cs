using System.Threading;
using HarmonyLib;
using MegaCrit.Sts2.Core.Logging;
using MegaCrit.Sts2.Core.Modding;
using STS2AIAgent.Game;
using STS2AIAgent.Patches;
using STS2AIAgent.Server;

namespace STS2AIAgent;

[ModInitializer(nameof(Initialize))]
public static class ModEntry
{
    private const string LogPrefix = "[STS2AIAgent]";
    private const string PatchStamp = "sts2-cloud-hotfix-20260410-r3";

    private static int _shutdownHooksRegistered;
    private static int _patchesApplied;

    public static void Initialize()
    {
        Log.Info($"{LogPrefix} Initializing {PatchStamp}");
        RegisterShutdownHooks();
        Log.Info($"{LogPrefix} Applying Harmony patches {PatchStamp}");
        ApplyPatches();
        GameThread.Initialize();
        GameEventService.Instance.Start();
        HttpServer.Instance.Start();
        Log.Info($"{LogPrefix} Ready");
    }

    private static void RegisterShutdownHooks()
    {
        if (Interlocked.Exchange(ref _shutdownHooksRegistered, 1) != 0)
        {
            return;
        }

        AppDomain.CurrentDomain.ProcessExit += (_, _) => Shutdown();
        AppDomain.CurrentDomain.DomainUnload += (_, _) => Shutdown();
    }

    private static void Shutdown()
    {
        try
        {
            GameEventService.Instance.Stop();
            HttpServer.Instance.Stop();
        }
        catch (Exception ex)
        {
            Log.Error($"{LogPrefix} Failed during shutdown: {ex}");
        }
    }

    private static void ApplyPatches()
    {
        if (Interlocked.Exchange(ref _patchesApplied, 1) != 0)
        {
            return;
        }

        try
        {
            var harmony = new Harmony("sts2-ai-agent.runtime-patches");
            CloudSyncBypassPatch.Apply(harmony);
        }
        catch (Exception ex)
        {
            Log.Error($"{LogPrefix} Failed to apply Harmony patches: {ex}");
        }
    }
}
