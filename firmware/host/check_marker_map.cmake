# Fail when the committed manifest fragment no longer matches the firmware's
# marker layout. Run with -DTOOL=<marker_map binary> -DEXPECTED=<json file>.

execute_process(COMMAND ${TOOL} OUTPUT_VARIABLE generated RESULT_VARIABLE status)
if(NOT status EQUAL 0)
    message(FATAL_ERROR "${TOOL} exited with ${status}")
endif()
file(READ ${EXPECTED} committed)

# Line endings differ by platform and checkout settings.
string(REPLACE "\r\n" "\n" generated "${generated}")
string(REPLACE "\r\n" "\n" committed "${committed}")

if(NOT generated STREQUAL committed)
    message(FATAL_ERROR
        "${EXPECTED} is out of date. Regenerate it with marker_map.\n"
        "Expected:\n${generated}\nFound:\n${committed}")
endif()
