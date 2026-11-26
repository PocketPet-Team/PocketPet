cmake_minimum_required(VERSION 3.20)
project(pocketpet_host LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(pet_state STATIC ../core/pet_state.c)
target_include_directories(pet_state PUBLIC ../core)

add_library(adv_policy STATIC ../core/adv_policy.c)
target_include_directories(adv_policy PUBLIC ../core)

add_executable(pet_replay replay.c)
target_link_libraries(pet_replay PRIVATE pet_state)

add_executable(adv_replay adv_replay.c)
target_link_libraries(adv_replay PRIVATE adv_policy)

include(CTest)
if(BUILD_TESTING)
    add_executable(pet_state_test pet_state_test.c)
    target_link_libraries(pet_state_test PRIVATE pet_state)
    add_test(NAME pet_state_test COMMAND pet_state_test)
    add_test(NAME pet_replay COMMAND pet_replay)

    add_executable(adv_policy_test adv_policy_test.c)
    target_link_libraries(adv_policy_test PRIVATE adv_policy)
    add_test(NAME adv_policy_test COMMAND adv_policy_test)
    add_test(NAME adv_replay COMMAND adv_replay)
endif()
