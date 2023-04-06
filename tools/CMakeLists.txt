cmake_minimum_required (VERSION 3.13.4)
project (LAVA VERSION 2.0.0)

#===============================================================================
# 1. LOAD LLVM CONFIGURATION
#===============================================================================
# Set this to a valid LLVM installation dir.
set(CT_Clang_INSTALL_DIR "/usr/lib/clang-14" CACHE PATH "Clang installation directory")

# # Add the location of ClangConfig.cmake to CMake search paths (so that
# # find_package can locate it)
list(APPEND CMAKE_PREFIX_PATH "${CT_Clang_INSTALL_DIR}/lib/cmake/clang/")

find_package(Clang REQUIRED CONFIG)

# This includes headers from LLVM and Clang - update the include paths
# accordingly.
include_directories(SYSTEM "${LLVM_INCLUDE_DIRS};${CLANG_INCLUDE_DIRS}")


set (CMAKE_CONFIGURATION_TYPES "Release" CACHE STRING "Configs" FORCE)

set(CMAKE_VERBOSE_MAKEFILE OFF)

CONFIGURE_FILE (
    "${PROJECT_SOURCE_DIR}/include/lava_version.h.in"
    "${PROJECT_SOURCE_DIR}/include/lava_version.h"
    )

add_subdirectory(lavaODB)
add_subdirectory(lavaDB)
add_subdirectory(lavaTool)
add_subdirectory(fbi)

