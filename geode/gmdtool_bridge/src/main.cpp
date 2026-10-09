// Windows-first experimental Geometry Dash bridge.
// All GD objects and Cocos state are accessed on the game main thread only.
#include <Geode/Geode.hpp>
#include <Geode/DefaultInclude.hpp>
#include <Geode/binding/PlayLayer.hpp>
#include <Geode/modify/PlayLayer.hpp>
#include <Geode/binding/PlayerObject.hpp>
#include <Geode/binding/GJEffectManager.hpp>
#include <matjson.hpp>
#include "bridge_transport.hpp"
#include <algorithm>
#include <atomic>
#include <exception>
#include <cstdint>
#include <vector>
#include <chrono>
#include <filesystem>
#include <future>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <memory>

using namespace geode::prelude;

#ifdef GEODE_IS_WINDOWS
namespace {
constexpr int PORT = 18731;

// These counters are safe to read from the network thread. They carry NO
// Geometry Dash or Cocos pointers and do not infer game-thread responsiveness
// from transport connectivity.
struct DispatchCounters {
    std::atomic<std::uint64_t> queued{0};
    std::atomic<std::uint64_t> started{0};
    std::atomic<std::uint64_t> completed{0};
    std::atomic<std::uint64_t> timedOut{0};
    std::atomic<std::int64_t> lastCompletedMs{0};
    std::atomic<std::int64_t> lastPostUpdateMs{0};
    std::atomic<std::uint64_t> postUpdates{0};
};
DispatchCounters counters;

std::int64_t monotonicMilliseconds() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

matjson::Value transportPing() {
    return matjson::makeObject({
        {"protocol", 1}, {"bridge", "gmdtool-geode"},
        {"online", true}, {"main_thread_checked", false}
    });
}

matjson::Value transportDiagnostics() {
    auto now = monotonicMilliseconds();
    auto completedAt = counters.lastCompletedMs.load();
    auto updatedAt = counters.lastPostUpdateMs.load();
    auto result = matjson::makeObject({
        {"transport_ok", true}, {"main_thread_checked", false},
        {"queued", static_cast<std::int64_t>(counters.queued.load())},
        {"started", static_cast<std::int64_t>(counters.started.load())},
        {"completed", static_cast<std::int64_t>(counters.completed.load())},
        {"timed_out", static_cast<std::int64_t>(counters.timedOut.load())},
        {"post_update_count", static_cast<std::int64_t>(counters.postUpdates.load())}
    });
    result["last_completed_ago_ms"] = completedAt ? matjson::Value(now - completedAt) : matjson::Value(nullptr);
    result["last_post_update_ago_ms"] = updatedAt ? matjson::Value(now - updatedAt) : matjson::Value(nullptr);
    return result;
}

// Count observations of PlayLayer::postUpdate, NOT physics ticks / TPS.
// All accesses to the scheduling state happen exclusively on GD's main thread.
struct InputEvent {
    std::uint64_t update;
    bool down;
    int button;
    bool player1;
};
struct RuntimeState {
    PlayLayer* owner = nullptr;
    std::uint64_t updates = 0;
    std::vector<InputEvent> inputs;
};
RuntimeState state;

void syncLevel(PlayLayer* layer) {
    if (state.owner != layer) {
        state = RuntimeState{};
        state.owner = layer;
    }
}

// The scheduler deliberately does not modify the engine's dt, physics rate,
// frame pacing, or render path. Same-update ordering follows insertion order.
class $modify(GmdtoolBridgePlayLayer, PlayLayer) {
    void postUpdate(float dt) {
        syncLevel(this);
        ++state.updates;
        ++counters.postUpdates;
        counters.lastPostUpdateMs.store(monotonicMilliseconds());
        auto it = state.inputs.begin();
        // Already sorted by requested update number; equal steps are stable.
        while (it != state.inputs.end() && it->update <= state.updates) {
            auto event = *it;
            it = state.inputs.erase(it);
            this->handleButton(event.down, event.button, event.player1);
        }
        PlayLayer::postUpdate(dt);
    }

    void resetLevel() {
        syncLevel(this);
        state.updates = 0;
        state.inputs.clear(); // A reset invalidates any queued attempt inputs.
        PlayLayer::resetLevel();
    }

    void onExit() {
        if (state.owner == this) state = RuntimeState{};
        PlayLayer::onExit();
    }
};

std::string makeToken() {
    std::random_device rd;
    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (int i = 0; i < 8; ++i) {
        stream << std::setw(4) << (rd() & 0xffff);
    }
    return stream.str();
}

matjson::Value readStatus(PlayLayer* play) {
    auto result = matjson::makeObject({{"playing", play != nullptr}});
    if (!play) return result;
    syncLevel(play);
    result["update_callbacks"] = static_cast<std::int64_t>(state.updates);
    result["queued_inputs"] = static_cast<int>(state.inputs.size());
    result["percent"] = play->getCurrentPercent();
    result["player_dead"] = play->m_playerDied;
    if (auto player = play->m_player1) {
        auto pos = player->getPosition();
        result["player1"] = matjson::makeObject({{"x", pos.x}, {"y", pos.y}});
    }
    if (auto player = play->m_player2) {
        auto pos = player->getPosition();
        result["player2"] = matjson::makeObject({{"x", pos.x}, {"y", pos.y}});
    }
    return result;
}

matjson::Value readItems(PlayLayer* play, matjson::Value const& params, bool allowEmpty) {
    auto ids = params["ids"].asArray();
    if (!ids || (!allowEmpty && ids.unwrap().empty()) || ids.unwrap().size() > 128) {
        return matjson::makeObject({{"_bridge_error", "ids must be an array of up to 128 items"}});
    }
    auto manager = play->m_effectManager;
    if (!manager) {
        return matjson::makeObject({{"_bridge_error", "Effect manager not ready"}});
    }
    matjson::Value values = matjson::makeObject({});
    for (auto const& element : ids.unwrap()) {
        auto parsedId = element.asInt();
        if (!parsedId || parsedId.unwrap() < 1 || parsedId.unwrap() > 9999) {
            return matjson::makeObject({{"_bridge_error", "item IDs must be 1..9999"}});
        }
        auto id = static_cast<int>(parsedId.unwrap());
        values[std::to_string(id)] = manager->countForItem(id);
    }
    return matjson::makeObject({{"values", values}});
}

matjson::Value resultFor(matjson::Value const& request) {
    auto method = request["method"].asString().unwrapOr("");
    auto play = PlayLayer::get();
    if (method == "status") {
        return readStatus(play);
    }
    if (method == "snapshot" && !play) {
        auto result = readStatus(play);
        result["values"] = matjson::makeObject({});
        return result;
    }
    if (!play) {
        return matjson::makeObject({{"_bridge_error", "No active PlayLayer; open a level first"}});
    }
    if (method == "reset_level") {
        play->resetLevel();
        return matjson::makeObject({{"requested", true}});
    }
    if (method == "input_queue_status") {
        syncLevel(play);
        return matjson::makeObject({
            {"update_callbacks", static_cast<std::int64_t>(state.updates)},
            {"queued_inputs", static_cast<int>(state.inputs.size())}
        });
    }
    if (method == "clear_inputs") {
        syncLevel(play);
        auto count = state.inputs.size();
        state.inputs.clear();
        return matjson::makeObject({{"cleared", static_cast<int>(count)}});
    }
    if (method == "schedule_inputs") {
        syncLevel(play);
        auto events = request["params"]["events"].asArray();
        if (!events || events.unwrap().empty() || events.unwrap().size() > 128 ||
            state.inputs.size() + events.unwrap().size() > 512) {
            return matjson::makeObject({{"_bridge_error", "events must have 1..128 entries; max 512 pending"}});
        }
        std::vector<InputEvent> batch;
        batch.reserve(events.unwrap().size());
        // Validate all entries before queuing any of them (atomic batch).
        for (auto const& entry : events.unwrap()) {
            auto update = entry["update"].asInt();
            auto down = entry["down"].asBool();
            auto button = entry["button"].asInt();
            auto player = entry["player"].asInt();
            if (!update || !down || !button || !player ||
                update.unwrap() <= static_cast<std::int64_t>(state.updates) ||
                update.unwrap() > static_cast<std::int64_t>(state.updates) + 100'000 ||
                button.unwrap() < 1 || button.unwrap() > 3 ||
                player.unwrap() < 1 || player.unwrap() > 2) {
                return matjson::makeObject({{"_bridge_error", "invalid update/down/button/player or update not in future"}});
            }
            batch.push_back({static_cast<std::uint64_t>(update.unwrap()),
                down.unwrap(), static_cast<int>(button.unwrap()), player.unwrap() == 1});
        }
        state.inputs.insert(state.inputs.end(), batch.begin(), batch.end());
        std::stable_sort(state.inputs.begin(), state.inputs.end(),
            [](InputEvent const& a, InputEvent const& b) { return a.update < b.update; });
        return matjson::makeObject({
            {"accepted", static_cast<int>(batch.size())},
            {"update_callbacks", static_cast<std::int64_t>(state.updates)},
            {"queued_inputs", static_cast<int>(state.inputs.size())}
        });
    }
    if (method == "items") {
        return readItems(play, request["params"], false);
    }
    if (method == "snapshot") {
        auto items = readItems(play, request["params"], true);
        if (items.contains("_bridge_error")) return items;
        auto snapshot = readStatus(play);
        snapshot["values"] = items["values"];
        return snapshot;
    }
    if (method == "input") {
        auto const& params = request["params"];
        auto down = params["down"].asBool();
        auto button = params["button"].asInt();
        auto player = params["player"].asInt();
        if (!down || !button || !player || button.unwrap() < 1 || button.unwrap() > 3 ||
            player.unwrap() < 1 || player.unwrap() > 2) {
            return matjson::makeObject({{"_bridge_error", "expected down:bool, button:1..3, player:1..2"}});
        }
        // The game's own input path; the moment this queued call runs is NOT a
        // guaranteed physics tick, unlike a future scheduled-replay feature.
        play->handleButton(down.unwrap(), static_cast<int>(button.unwrap()), player.unwrap() == 1);
        return matjson::makeObject({{"accepted", true}});
    }
    return matjson::makeObject({{"_bridge_error", "unknown method"}});
}

matjson::Value onRequest(matjson::Value const& request, std::string const& token) {
    auto id = request["id"];
    auto reply = matjson::makeObject({{"id", id}, {"ok", false}});
    if (request["token"].asString().unwrapOr("") != token) {
        reply["error"] = "authentication failed";
        return reply;
    }
    if (!request["method"].isString()) {
        reply["error"] = "method must be a string";
        return reply;
    }
    auto method = request["method"].asString().unwrapOr("");
    // Transport-only methods never touch GD/Cocos objects, so must not wait for
    // the main-thread queue. This is especially important when GD loses focus.
    if (method == "ping" || method == "bridge_health") {
        reply["ok"] = true;
        reply["result"] = method == "ping" ? transportPing() : transportDiagnostics();
        return reply;
    }
    // The network thread must never dereference any GD/Cocos object.
    auto promise = std::make_shared<std::promise<matjson::Value>>();
    auto future = promise->get_future();
    // A timed-out command should not mutate GD later just because it was
    // still waiting in the main-thread queue. A command that has already
    // *started* is not cancellable; callers must treat timeouts as uncertain.
    auto pending = std::make_shared<std::atomic_bool>(true);
    ++counters.queued;
    geode::queueInMainThread([request, promise, pending] {
        if (!pending->exchange(false)) return; // timeout cancelled before start
        ++counters.started;
        matjson::Value result;
        try {
            result = resultFor(request);
        } catch (std::exception const& e) {
            result = matjson::makeObject({{"_bridge_error", e.what()}});
        } catch (...) {
            result = matjson::makeObject({{"_bridge_error", "unhandled main-thread exception"}});
        }
        counters.lastCompletedMs.store(monotonicMilliseconds());
        ++counters.completed;
        promise->set_value(std::move(result));
    });
    if (future.wait_for(std::chrono::seconds(3)) != std::future_status::ready) {
        pending->store(false);
        ++counters.timedOut;
        reply["error"] = "main thread response timed out (game may be unfocused, paused, or blocked; check bridge_health)";
        return reply;
    }
    auto result = future.get();
    if (result.contains("_bridge_error")) {
        reply["error"] = result["_bridge_error"];
        return reply;
    }
    reply["ok"] = true;
    reply["result"] = result;
    return reply;
}

// Only protocol parsing and authentication run on the worker thread.
// Every GD / Cocos call happens in resultFor() via queueInMainThread.
std::string handleWireRequest(std::string const& line, std::string const& token) {
    matjson::Value reply = matjson::makeObject({
        {"id", nullptr}, {"ok", false}, {"error", "malformed request"}
    });
    try {
        auto parsed = matjson::parse(line);
        if (parsed && parsed.unwrap().isObject()) {
            reply = onRequest(parsed.unwrap(), token);
        }
    } catch (std::exception const& e) {
        reply["error"] = e.what();
    }
    return reply.dump(matjson::NO_INDENTATION) + "\n";
}

// jthread owns the server. Never detach a worker running code from our DLL:
// its stop token and bounded socket waits allow a clean unload.
std::jthread serverThread;
} // anonymous namespace

$on_mod(Loaded) {
    if (!Mod::get()->getSettingValue<bool>("enabled")) return;
    auto token = makeToken();
    auto session = Mod::get()->getSaveDir() / "bridge-session.json";
    std::error_code error;
    std::filesystem::create_directories(session.parent_path(), error);
    if (error) {
        log::error("gmdtool bridge: cannot create save directory: {}", error.message());
        return;
    }
    std::filesystem::remove(session, error);
    log::info("gmdtool bridge session descriptor (when ready): {}", session.string());
    auto descriptor = matjson::makeObject({
        {"protocol", 1}, {"host", "127.0.0.1"}, {"port", PORT}, {"token", token}
    }).dump(matjson::NO_INDENTATION);
    serverThread = std::jthread([token = std::move(token), session, descriptor](std::stop_token stop) {
        gmdtool::transport::runLocalServer(stop, PORT, session, descriptor,
            [token](std::string const& line) { return handleWireRequest(line, token); });
    });
}
#endif
