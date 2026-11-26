#include "pet_state.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition)                                                    \
    do {                                                                    \
        if (!(condition)) {                                                 \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
            exit(EXIT_FAILURE);                                             \
        }                                                                   \
    } while (0)

static enum pet_action step(struct pet_state *state, enum pet_event event,
                            uint64_t now_ms)
{
    enum pet_action action;
    CHECK(pet_step(state, event, now_ms, &action));
    return action;
}

static void test_idle_replay(void)
{
    struct pet_state state;
    pet_init(&state, 0);

    CHECK(step(&state, PET_EVENT_LINK_CONNECTED, 0) == PET_ACTION_NONE);
    CHECK(state.mood == 100);
    CHECK(step(&state, PET_EVENT_BUTTON, 1800000) == PET_ACTION_REFRESH_DISPLAY);
    CHECK(state.mood == 98);
    CHECK(step(&state, PET_EVENT_ROUTINE_SYNC_DUE, 1800000) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_FIND, 1800000) == PET_ACTION_START_HAPTIC);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 1800000) == PET_ACTION_SEND_STATE);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 1800000) == PET_ACTION_NONE);
}

static void test_partial_decay_and_mood_bounds(void)
{
    struct pet_state state;
    pet_init(&state, 1000);

    CHECK(step(&state, PET_EVENT_BUTTON, 1000) == PET_ACTION_REFRESH_DISPLAY);
    CHECK(state.mood == 100);
    CHECK(step(&state, PET_EVENT_LINK_CONNECTED, 121000) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_ROUTINE_SYNC_DUE, 300999) == PET_ACTION_NONE);
    CHECK(state.mood == 100);
    CHECK(step(&state, PET_EVENT_FIND, 301000) == PET_ACTION_START_HAPTIC);
    CHECK(state.mood == 99);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 611000) == PET_ACTION_SEND_STATE);
    CHECK(state.mood == 98);

    CHECK(step(&state, PET_EVENT_LINK_DISCONNECTED, UINT64_MAX) == PET_ACTION_NONE);
    CHECK(state.mood == 0);
    CHECK(step(&state, PET_EVENT_BUTTON, UINT64_MAX) == PET_ACTION_REFRESH_DISPLAY);
    CHECK(state.mood == 4);
}

static void test_sync_survives_link_loss(void)
{
    struct pet_state state;
    pet_init(&state, 0);

    CHECK(step(&state, PET_EVENT_LINK_CONNECTED, 1) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_ROUTINE_SYNC_DUE, 2) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_ROUTINE_SYNC_DUE, 3) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_LINK_DISCONNECTED, 4) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_FIND, 5) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 6) == PET_ACTION_NONE);

    CHECK(step(&state, PET_EVENT_LINK_CONNECTED, 7) == PET_ACTION_NONE);
    CHECK(step(&state, PET_EVENT_BUTTON, 8) == PET_ACTION_REFRESH_DISPLAY);
    CHECK(step(&state, PET_EVENT_FIND, 8) == PET_ACTION_START_HAPTIC);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 8) == PET_ACTION_SEND_STATE);
    CHECK(step(&state, PET_EVENT_FLUSH_ROUTINE_SYNC, 9) == PET_ACTION_NONE);
}

static void test_rejects_invalid_input(void)
{
    struct pet_state state;
    pet_init(&state, 1000);
    enum pet_action action = PET_ACTION_SEND_STATE;

    CHECK(!pet_step(&state, PET_EVENT_LINK_CONNECTED, 999, &action));
    CHECK(!pet_step(&state, (enum pet_event)99, 1000000, &action));
    CHECK(action == PET_ACTION_SEND_STATE);
    CHECK(state.last_event_ms == 1000);
    CHECK(state.last_decay_ms == 1000);
    CHECK(state.mood == 100);
    CHECK(!state.connected);
    CHECK(!state.routine_sync_pending);
    CHECK(step(&state, PET_EVENT_BUTTON, 301000) == PET_ACTION_REFRESH_DISPLAY);
}

int main(void)
{
    test_idle_replay();
    test_partial_decay_and_mood_bounds();
    test_sync_survives_link_loss();
    test_rejects_invalid_input();
    return EXIT_SUCCESS;
}
