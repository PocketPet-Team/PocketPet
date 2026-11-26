cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(pocketpet_app LANGUAGES C)

# The portable cores are shared with the host replays in ../host.
set(POCKETPET_CORE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../core)

target_include_directories(app PRIVATE ${POCKETPET_CORE_DIR})
target_sources(app PRIVATE
    src/main.c
    src/pet_service.c
    ${POCKETPET_CORE_DIR}/pet_state.c
    ${POCKETPET_CORE_DIR}/adv_policy.c
)
