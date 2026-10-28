*** Settings ***
Documentation       Smoke test exercising the standard EdgeLens lifecycle.
Library             EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=SUITE
Suite Teardown      Release Device


*** Variables ***
${MODEL_URL}        https://example.com/face.cvimodel
${MIN_FPS}          15
${MAX_LATENCY_P95}  100


*** Test Cases ***
Camera Boots And Responds
    Request Device    device_type=recamera-2002    os=stock-os
    ${info}=    Get Device Info
    Should Not Be Empty    ${info}[hostname]

Deploy And Verify Inference
    [Documentation]    Deploys a model, starts inference, verifies fps and latency.
    Deploy Model    ${MODEL_URL}
    Start Inference
    ${stats}=    Run Inference    duration=30
    Should Be True    ${stats}[fps][avg] > ${MIN_FPS}    msg=avg fps below threshold
    Should Be True    ${stats}[latency_ms][p95] < ${MAX_LATENCY_P95}    msg=p95 latency too high
    Stop Inference

Display Round Trip
    Show On Display    https://example.com/test-pattern.png
    ${status}=    Get Display Status
    Should Be Equal    ${status}[state]    showing
    Stop Display
