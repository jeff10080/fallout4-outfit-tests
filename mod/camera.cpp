#include <atomic>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <numbers>
#include <cstdlib>
#include <sstream>
#include <vector>
#include <Windows.h>

#include "f4se_common/f4se_version.h"
#include "f4se/GameCamera.h"
#include "f4se/GameThreads.h"
#include "f4se/PapyrusNativeFunctions.h"
#include "f4se/PapyrusVM.h"
#include "f4se/PluginAPI.h"

namespace {

// Fallout 4 1.11.240 Steam. The singleton matches F4SE 0.7.9's GameCamera.cpp.
// The toggle is CommonLibF4's PlayerCamera::ToggleFreeCameraMode, Address Library ID 2248368.
constexpr std::uintptr_t playerCameraRva = 0x030E6E58;
constexpr std::uintptr_t toggleFreeCameraRva = 0x01027920;
// Confirmed at the 1.11.240 Tab handler and Pip-Boy menu call sites.
constexpr std::uintptr_t pipboyManagerRva = 0x031F0888;
constexpr std::uintptr_t playPipboyOpenRva = 0x00B4F980;
constexpr std::uintptr_t playPipboyCloseRva = 0x00B50580;
constexpr char scriptName[] = "OutfitTestCamera";

struct CameraShot {
    float x;
    float y;
    float z;
    float pitch;
    float yaw;
};

struct FreeCameraState : TESCameraState {
    CameraShot shot;
};
static_assert(sizeof(TESCameraState) == 0x28);

enum class ShotStatus : SInt32 { failed = -1, idle, pending, active };

std::atomic shotStatus{ShotStatus::idle};
F4SETaskInterface* tasks = nullptr;
PlayerCamera* shotCamera = nullptr;
FreeCameraState* shotState = nullptr;
CameraShot fixedShot{};
std::filesystem::path runFolder;
std::string outfitPlugin;
SInt32 outfitForm = 0;
std::vector<std::pair<std::string, SInt32>> extraPieces;
SInt32 scenario = 0;
SInt32 cameraOverride = -1;

struct CameraPreset {
    const char* name;
    float eyeForward, eyeRight, eyeHeight;
    float targetForward, targetRight, targetHeight;
};

constexpr std::array presets{
    CameraPreset{"wrist-right", 80, 108, 113, 25, 16, 101},
    CameraPreset{"wrist-inner", 104, -38, 98, 32, 16, 102},
    CameraPreset{"front", 225, 0, 83, 0, 0, 76},
    CameraPreset{"back", -225, 0, 83, 0, 0, 76},
    CameraPreset{"right", 0, 225, 83, 0, 0, 76},
    CameraPreset{"left", 0, -225, 83, 0, 0, 76},
    CameraPreset{"legs-right", 6, 158, 53, 0, 0, 55},
    CameraPreset{"route-profile", 0, 292, 83, 0, 0, 70},
    CameraPreset{"route-rear", -110, 169, 79, 0, 0, 66},
    CameraPreset{"head", 78, 20, 131, 0, 0, 131},
    CameraPreset{"shoulder-right", 48, 79, 119, 0, 17, 114},
    CameraPreset{"arm-right", 63, 91, 94, 8, 18, 88},
    CameraPreset{"torso", 116, 10, 106, 0, 0, 102},
    CameraPreset{"upper-back", -116, -10, 106, 0, 0, 102},
    CameraPreset{"hips", 75, 79, 75, 0, 0, 68},
    CameraPreset{"knees-right", 17, 94, 39, 0, 0, 39},
    CameraPreset{"feet", 73, 51, 24, 0, 0, 15},
    CameraPreset{"shoulder-left", 48, -79, 119, 0, -17, 114},
    CameraPreset{"arm-left", 63, -91, 94, 8, -18, 88},
    CameraPreset{"wrist-left", 80, -108, 113, 25, -16, 101},
    CameraPreset{"legs-left", 6, -158, 53, 0, 0, 55},
    CameraPreset{"knees-left", 17, -94, 39, 0, 0, 39},
    CameraPreset{"rifle-front", 126, -124, 111, 40, 0, 105},
};

SInt32 AutomationState(StaticFunctionTag*)
{
    if (runFolder.empty()) {
        return 0;
    }
    std::error_code error;
    if (std::filesystem::exists(runFolder / L"quit", error)) {
        return 3;
    }
    return std::filesystem::exists(runFolder / L"go", error) ? 2 : 1;
}

BSFixedString OutfitPlugin(StaticFunctionTag*)
{
    return BSFixedString(outfitPlugin.c_str());
}

SInt32 OutfitForm(StaticFunctionTag*) { return outfitForm; }
SInt32 ExtraPieceCount(StaticFunctionTag*) { return static_cast<SInt32>(extraPieces.size()); }

BSFixedString ExtraPiecePlugin(StaticFunctionTag*, SInt32 index)
{
    return index >= 0 && static_cast<size_t>(index) < extraPieces.size()
        ? BSFixedString(extraPieces[index].first.c_str()) : BSFixedString();
}

SInt32 ExtraPieceForm(StaticFunctionTag*, SInt32 index)
{
    return index >= 0 && static_cast<size_t>(index) < extraPieces.size() ? extraPieces[index].second : 0;
}
SInt32 Scenario(StaticFunctionTag*) { return scenario; }
SInt32 CameraOverride(StaticFunctionTag*) { return cameraOverride; }

BSFixedString PresetName(StaticFunctionTag*, SInt32 preset)
{
    return BSFixedString(preset >= 0 && preset < static_cast<SInt32>(presets.size()) ? presets[preset].name : "");
}

void Report(StaticFunctionTag*, BSFixedString phase)
{
    if (!runFolder.empty()) {
        std::ofstream(runFolder / L"phases.log", std::ios::app) << phase.c_str() << '\n';
    }
}

PlayerCamera* GetPlayerCamera()
{
    const auto base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    return *reinterpret_cast<PlayerCamera**>(base + playerCameraRva);
}

void ToggleFreeCamera(PlayerCamera* camera)
{
    using Toggle = void (*)(PlayerCamera*, bool);
    const auto base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    reinterpret_cast<Toggle>(base + toggleFreeCameraRva)(camera, false);
}

CameraShot MakeShot(const CameraPreset& preset, float x, float y, float z, float actorYaw)
{
    // Skyrim/Fallout heading starts at +Y and increases toward +X.
    constexpr float tau = 2.0f * std::numbers::pi_v<float>;
    const float heading = actorYaw * (tau / 360.0f);
    const float forwardX = std::sin(heading);
    const float forwardY = std::cos(heading);
    const float rightX = forwardY;
    const float rightY = -forwardX;

    const float eyeX = x + preset.eyeForward * forwardX + preset.eyeRight * rightX;
    const float eyeY = y + preset.eyeForward * forwardY + preset.eyeRight * rightY;
    const float dx = (preset.targetForward - preset.eyeForward) * forwardX + (preset.targetRight - preset.eyeRight) * rightX;
    const float dy = (preset.targetForward - preset.eyeForward) * forwardY + (preset.targetRight - preset.eyeRight) * rightY;
    const float yaw = std::atan2(dx, dy);
    const float pitch = std::atan2(preset.eyeHeight - preset.targetHeight, std::hypot(dx, dy));
    return {eyeX, eyeY, z + preset.eyeHeight, pitch, yaw < 0.0f ? yaw + tau : yaw};
}

void RestoreCamera()
{
    const auto camera = GetPlayerCamera();
    if (shotState && camera == shotCamera && camera->cameraState == shotState) {
        ToggleFreeCamera(camera);
    }
    shotCamera = nullptr;
    shotState = nullptr;
    shotStatus = ShotStatus::idle;
}

class BeginShotTask final : public ITaskDelegate {
public:
    explicit BeginShotTask(CameraShot shot) : shot_(shot) {}

    void Run() override
    {
        if (shotStatus != ShotStatus::pending) {
            return;
        }
        const auto camera = GetPlayerCamera();
        if (!camera || !camera->cameraState || !camera->cameraStates[PlayerCamera::kCameraState_Free] ||
            camera->cameraState == camera->cameraStates[PlayerCamera::kCameraState_Free]) {
            shotStatus = ShotStatus::failed;
            return;
        }
        auto* freeState = static_cast<FreeCameraState*>(camera->cameraStates[PlayerCamera::kCameraState_Free]);
        ToggleFreeCamera(camera);
        if (camera->cameraState != freeState) {
            shotStatus = ShotStatus::failed;
            return;
        }
        shotCamera = camera;
        shotState = freeState;
        fixedShot = shot_;
        shotState->shot = fixedShot;
        shotStatus = ShotStatus::active;
    }

private:
    CameraShot shot_;
};

class MaintainShotTask final : public ITaskDelegate {
    void Run() override
    {
        if (shotStatus != ShotStatus::active) {
            return;
        }
        const auto camera = GetPlayerCamera();
        if (camera != shotCamera || camera->cameraState != shotState) {
            shotCamera = nullptr;
            shotState = nullptr;
            shotStatus = ShotStatus::failed;
            return;
        }
        shotState->shot = fixedShot;
    }
};

class RestoreCameraTask final : public ITaskDelegate {
    void Run() override { RestoreCamera(); }
};

class PipboyTask final : public ITaskDelegate {
public:
    explicit PipboyTask(bool open) : open_(open) {}

    void Run() override
    {
        const auto base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        auto* manager = *reinterpret_cast<void**>(base + pipboyManagerRva);
        if (!manager) {
            return;
        }
        if (open_) {
            BSFixedString menu("PipboyMenu");
            using Open = void (*)(void*, const BSFixedString&);
            reinterpret_cast<Open>(base + playPipboyOpenRva)(manager, menu);
            menu.Release();
        } else {
            using Close = void (*)(void*, bool);
            reinterpret_cast<Close>(base + playPipboyCloseRva)(manager, false);
        }
    }

private:
    bool open_;
};

void SetPipboy(StaticFunctionTag*, bool open)
{
    tasks->AddTask(new PipboyTask(open));
}

bool BeginPreset(StaticFunctionTag*, SInt32 preset, float x, float y, float z, float yaw)
{
    auto expected = ShotStatus::idle;
    if (preset < 0 || preset >= static_cast<SInt32>(presets.size()) ||
        !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || !std::isfinite(yaw) ||
        !shotStatus.compare_exchange_strong(expected, ShotStatus::pending)) {
        return false;
    }
    tasks->AddTask(new BeginShotTask(MakeShot(presets[preset], x, y, z, yaw)));
    return true;
}

SInt32 Status(StaticFunctionTag*)
{
    return static_cast<SInt32>(shotStatus.load());
}

void EndShot(StaticFunctionTag*)
{
    tasks->AddTask(new RestoreCameraTask());
}

bool RegisterPapyrus(VirtualMachine* vm)
{
    vm->RegisterFunction(new NativeFunction5<StaticFunctionTag, bool, SInt32, float, float, float, float>("BeginPreset", scriptName, BeginPreset, vm));
    vm->RegisterFunction(new NativeFunction1<StaticFunctionTag, BSFixedString, SInt32>("PresetName", scriptName, PresetName, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("Status", scriptName, Status, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, void>("EndShot", scriptName, EndShot, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("AutomationState", scriptName, AutomationState, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, BSFixedString>("OutfitPlugin", scriptName, OutfitPlugin, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("OutfitForm", scriptName, OutfitForm, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("ExtraPieceCount", scriptName, ExtraPieceCount, vm));
    vm->RegisterFunction(new NativeFunction1<StaticFunctionTag, BSFixedString, SInt32>("ExtraPiecePlugin", scriptName, ExtraPiecePlugin, vm));
    vm->RegisterFunction(new NativeFunction1<StaticFunctionTag, SInt32, SInt32>("ExtraPieceForm", scriptName, ExtraPieceForm, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("Scenario", scriptName, Scenario, vm));
    vm->RegisterFunction(new NativeFunction0<StaticFunctionTag, SInt32>("CameraOverride", scriptName, CameraOverride, vm));
    vm->RegisterFunction(new NativeFunction1<StaticFunctionTag, void, bool>("SetPipboy", scriptName, SetPipboy, vm));
    vm->RegisterFunction(new NativeFunction1<StaticFunctionTag, void, BSFixedString>("Report", scriptName, Report, vm));
    return true;
}

void OnF4SEMessage(F4SEMessagingInterface::Message* message)
{
    if (message->type == F4SEMessagingInterface::kMessage_PreLoadGame ||
        message->type == F4SEMessagingInterface::kMessage_NewGame) {
        RestoreCamera();
    }
}

}

extern "C" __declspec(dllexport) constinit F4SEPluginVersionData F4SEPlugin_Version{
    .dataVersion = F4SEPluginVersionData::kVersion,
    .pluginVersion = 1,
    .name = "OutfitTestCamera",
    .author = "Fallout 4 Outfit Tests",
    .compatibleVersions = {RUNTIME_VERSION_1_11_240},
};

extern "C" __declspec(dllexport) bool F4SEPlugin_Load(const F4SEInterface* f4se)
{
    if (f4se->isEditor || f4se->runtimeVersion != RUNTIME_VERSION_1_11_240) {
        return false;
    }
    if (const auto* folder = _wgetenv(L"FO4_OUTFIT_RUN"); folder && *folder) {
        runFolder = folder;
        if (const auto* plugin = std::getenv("FO4_OUTFIT_PLUGIN")) {
            outfitPlugin = plugin;
        }
        if (const auto* form = std::getenv("FO4_OUTFIT_FORM")) {
            outfitForm = std::strtol(form, nullptr, 10);
        }
        std::ifstream pieces(runFolder / L"pieces.tsv");
        std::string plugin;
        std::string form;
        while (std::getline(pieces, plugin, '\t') && std::getline(pieces, form)) {
            extraPieces.emplace_back(plugin, std::strtol(form.c_str(), nullptr, 10));
        }
        if (const auto* selection = std::getenv("FO4_OUTFIT_SCENARIO")) {
            scenario = std::strtol(selection, nullptr, 10);
        }
        if (const auto* camera = std::getenv("FO4_OUTFIT_CAMERA")) {
            cameraOverride = std::strtol(camera, nullptr, 10);
        }
    }
    tasks = static_cast<F4SETaskInterface*>(f4se->QueryInterface(kInterface_Task));
    auto papyrus = static_cast<F4SEPapyrusInterface*>(f4se->QueryInterface(kInterface_Papyrus));
    auto messages = static_cast<F4SEMessagingInterface*>(f4se->QueryInterface(kInterface_Messaging));
    if (!tasks || tasks->interfaceVersion < 2 || !papyrus || !messages ||
        !messages->RegisterListener(f4se->GetPluginHandle(), "F4SE", OnF4SEMessage) ||
        !papyrus->Register(RegisterPapyrus)) {
        return false;
    }
    tasks->AddTaskPermanent(new MaintainShotTask());
    return true;
}
