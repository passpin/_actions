// Winsock2 MUST be the first Windows header in this translation unit.
// Geode's precompiled headers can include legacy winsock.h: CMake skips PCH
// for this file to keep the two incompatible declarations apart.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

#include "bridge_transport.hpp"
#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <utility>
#include <cstdio>

namespace gmdtool::transport {
namespace {
constexpr std::size_t kMaxRequestBytes = 16'384;

void receiveAndReply(SOCKET client, RequestHandler const& handler) {
    DWORD milliseconds = 4500;
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO,
               reinterpret_cast<char const*>(&milliseconds), sizeof(milliseconds));
    setsockopt(client, SOL_SOCKET, SO_SNDTIMEO,
               reinterpret_cast<char const*>(&milliseconds), sizeof(milliseconds));
    std::string line;
    line.reserve(512);
    for (;;) {
        char c{};
        if (recv(client, &c, 1, 0) != 1) return;
        if (c == '\n') break;
        if (line.size() >= kMaxRequestBytes) return;
        line.push_back(c);
    }
    std::string response;
    try { response = handler(line); }
    catch (...) { response = R"({"id":null,"ok":false,"error":"worker exception"})" "\n"; }
    std::size_t sent = 0;
    while (sent < response.size()) {
        int amount = send(client, response.data() + sent,
                          static_cast<int>(response.size() - sent), 0);
        if (amount <= 0) return;
        sent += static_cast<std::size_t>(amount);
    }
}

struct WinSockStartup {
    bool initialized = false;
    WinSockStartup() {
        WSADATA info{};
        initialized = WSAStartup(MAKEWORD(2, 2), &info) == 0;
    }
    ~WinSockStartup() { if (initialized) WSACleanup(); }
    WinSockStartup(WinSockStartup const&) = delete;
    WinSockStartup& operator=(WinSockStartup const&) = delete;
};

struct ScopedSocket {
    SOCKET handle = INVALID_SOCKET;
    ~ScopedSocket() { if (handle != INVALID_SOCKET) closesocket(handle); }
    ScopedSocket() = default;
    explicit ScopedSocket(SOCKET socket) : handle(socket) {}
    ScopedSocket(ScopedSocket const&) = delete;
    ScopedSocket& operator=(ScopedSocket const&) = delete;
};
}

void runLocalServer(std::stop_token stop, std::uint16_t port,
                    std::filesystem::path const& sessionPath,
                    std::string const& sessionJson,
                    RequestHandler handler) {
    WinSockStartup socketContext;
    if (!socketContext.initialized) {
        std::fputs("gmdtool: WSAStartup failed\n", stderr);
        return;
    }
    {
        ScopedSocket server(socket(AF_INET, SOCK_STREAM, IPPROTO_TCP));
        if (server.handle == INVALID_SOCKET) {
            std::fputs("gmdtool: cannot create TCP socket\n", stderr);
        } else {
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (bind(server.handle, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 ||
                listen(server.handle, 4) != 0) {
                std::fputs("gmdtool: cannot bind/listen on loopback port\n", stderr);
            } else {
                {
                    std::ofstream out(sessionPath, std::ios::binary | std::ios::trunc);
                    if (!out || !(out << sessionJson)) {
                        std::fputs("gmdtool: could not write session descriptor\n", stderr);
                        return;
                    }
                }
                while (!stop.stop_requested()) {
                    fd_set fds{};
                    FD_ZERO(&fds);
                    FD_SET(server.handle, &fds);
                    timeval timeout{};
                    timeout.tv_sec = 0;
                    timeout.tv_usec = 200'000;
                    int ready = select(0, &fds, nullptr, nullptr, &timeout);
                    if (ready <= 0) continue;
                    ScopedSocket client(accept(server.handle, nullptr, nullptr));
                    if (client.handle != INVALID_SOCKET && !stop.stop_requested()) {
                        receiveAndReply(client.handle, handler);
                    }
                }
                // Don't leave a stale authentication token after a normal unload.
                std::error_code ec;
                std::filesystem::remove(sessionPath, ec);
            }
        }
    }
}
}
