#pragma once
#include <cstdint>
#include <filesystem>
#include <functional>
#include <stop_token>
#include <string>

// No Geometry Dash, Cocos or Geode headers here. This is a standalone
// Windows networking translation unit; it is compiled WITHOUT Geode PCH.
namespace gmdtool::transport {
using RequestHandler = std::function<std::string(std::string const&)>;
void runLocalServer(std::stop_token stop, std::uint16_t port,
                    std::filesystem::path const& sessionPath,
                    std::string const& sessionJson,
                    RequestHandler handler);
}
