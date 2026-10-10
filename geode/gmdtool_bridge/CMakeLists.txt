cmake_minimum_required(VERSION 3.25)
project(gmdtool_bridge VERSION 0.13.1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(${PROJECT_NAME} SHARED
    src/main.cpp
    src/bridge_transport.cpp
    src/auto_update.cpp
)
if(NOT DEFINED ENV{GEODE_SDK})
    message(FATAL_ERROR "Set GEODE_SDK to your installed Geode SDK")
endif()
add_subdirectory($ENV{GEODE_SDK} ${CMAKE_CURRENT_BINARY_DIR}/geode)
# The network-only file must NOT inherit Geode's injected precompiled headers.
# Otherwise Windows's legacy winsock.h is loaded before winsock2.h.
set_source_files_properties(src/bridge_transport.cpp PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
if(WIN32)
    target_link_libraries(${PROJECT_NAME} ws2_32 user32 bcrypt comctl32)
endif()
setup_geode_mod(${PROJECT_NAME})
