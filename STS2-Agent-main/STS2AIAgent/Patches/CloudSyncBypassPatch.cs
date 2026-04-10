using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using HarmonyLib;
using MegaCrit.Sts2.Core.Logging;

namespace STS2AIAgent.Patches;

internal static class CloudSyncBypassPatch
{
    private const string LogPrefix = "[STS2AIAgent]";
    private const string PatchStamp = "sts2-cloud-hotfix-20260410-r3";

    public static void Apply(Harmony harmony)
    {
        var saveManagerType = AccessTools.TypeByName("MegaCrit.Sts2.Core.Saves.SaveManager");
        var saveManagerSyncMethod = saveManagerType is null
            ? null
            : AccessTools.Method(saveManagerType, "SyncCloudToLocal", []);
        var cloudSaveStoreType = AccessTools.TypeByName("MegaCrit.Sts2.Core.Saves.CloudSaveStore");
        var cloudSaveStoreSyncMethod = cloudSaveStoreType is null
            ? null
            : AccessTools.Method(cloudSaveStoreType, "SyncCloudToLocal", [typeof(string)]);
        var profileSaveManagerType = AccessTools.TypeByName("MegaCrit.Sts2.Core.Saves.Managers.ProfileSaveManager");
        var profileSaveManagerSyncMethod = profileSaveManagerType is null
            ? null
            : AccessTools.Method(profileSaveManagerType, "SyncCloudToLocal", []);
        var steamRemoteSaveType = AccessTools.TypeByName("MegaCrit.Sts2.Core.Platform.Steam.SteamRemoteSaveStore");
        var readFileAsyncMethod = steamRemoteSaveType is null
            ? null
            : AccessTools.Method(steamRemoteSaveType, "ReadFileAsync", [typeof(string)]);

        PatchMethod(
            harmony,
            saveManagerSyncMethod,
            nameof(SkipSaveManagerCloudSync),
            "SaveManager.SyncCloudToLocal"
        );
        PatchMethod(
            harmony,
            cloudSaveStoreSyncMethod,
            nameof(SkipCloudSaveStorePathSync),
            "CloudSaveStore.SyncCloudToLocal(string)"
        );
        PatchMethod(
            harmony,
            profileSaveManagerSyncMethod,
            nameof(SkipProfileSaveManagerCloudSync),
            "ProfileSaveManager.SyncCloudToLocal"
        );
        PatchMethod(
            harmony,
            readFileAsyncMethod,
            nameof(InterceptProfileReadAsync),
            "SteamRemoteSaveStore.ReadFileAsync(string)"
        );
    }

    private static void PatchMethod(Harmony harmony, MethodBase? original, string prefixMethodName, string description)
    {
        if (original is null)
        {
            Log.Warn($"{LogPrefix} {PatchStamp} Could not find {description}; patch not applied.");
            return;
        }

        harmony.Patch(
            original,
            prefix: new HarmonyMethod(typeof(CloudSyncBypassPatch), prefixMethodName)
        );
        Log.Info($"{LogPrefix} {PatchStamp} Installed patch for {description}.");
    }

    private static bool SkipSaveManagerCloudSync(ref Task __result)
    {
        Log.Warn($"{LogPrefix} {PatchStamp} Skipping SaveManager.SyncCloudToLocal.");
        __result = Task.CompletedTask;
        return false;
    }

    private static bool SkipCloudSaveStorePathSync(string path, ref Task __result)
    {
        Log.Warn($"{LogPrefix} {PatchStamp} Skipping CloudSaveStore.SyncCloudToLocal for '{path}'.");
        __result = Task.CompletedTask;
        return false;
    }

    private static bool SkipProfileSaveManagerCloudSync(ref Task __result)
    {
        Log.Warn($"{LogPrefix} {PatchStamp} Skipping ProfileSaveManager.SyncCloudToLocal.");
        __result = Task.CompletedTask;
        return false;
    }

    private static bool InterceptProfileReadAsync(string path, ref Task<string> __result)
    {
        if (!string.Equals(path, "profile.save", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        const string fallbackProfile = "{\n  \"last_profile_id\": 1,\n  \"schema_version\": 2\n}";
        Log.Warn($"{LogPrefix} {PatchStamp} Returning fallback content for SteamRemoteSaveStore.ReadFileAsync(profile.save).");
        __result = Task.FromResult(fallbackProfile);
        return false;
    }
}
