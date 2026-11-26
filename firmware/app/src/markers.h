#ifndef POCKETPET_MARKERS_H
#define POCKETPET_MARKERS_H

#include <stdbool.h>

#include "marker.h"

/*
 * Drives the logic lines a PPK2 records next to the current, using the layout
 * in marker.h. Without CONFIG_POCKETPET_PPK2_MARKERS every call does nothing.
 */
#ifdef CONFIG_POCKETPET_PPK2_MARKERS

/* Configure the lines and drive them low; returns 0 or a negative errno. */
int markers_init(void);

/* Select the operating state. Safe from interrupts and any thread. */
void markers_set_state(enum marker_state state);

/*
 * Raise or lower an event line. Safe from interrupts and any thread. A line
 * has no count: a second start while it is high joins the pulse already open.
 */
void markers_set_event(enum marker_event event, bool active);

#else

static inline int markers_init(void)
{
    return 0;
}

static inline void markers_set_state(enum marker_state state)
{
    (void)state;
}

static inline void markers_set_event(enum marker_event event, bool active)
{
    (void)event;
    (void)active;
}

#endif

#endif
