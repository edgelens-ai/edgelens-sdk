*** Settings ***
Resource          ../resources/common.resource
Suite Setup       Open Session    device_type=recamera-2002    os=stock-os
Suite Teardown    Release Session

*** Test Cases ***
Face Detector Hits Latency Budget
    [Tags]    latency    regression
    Deploy Model    ${CURDIR}/../models/face.cvimodel
    ${stats}=    Run Inference    duration=30
    Should Be True
    ...    ${stats.latency_ms.p95} < 100
    ...    msg=p95 latency ${stats.latency_ms.p95}ms exceeds 100ms budget

Face Detector Holds FPS Floor
    [Tags]    throughput    regression
    Deploy Model    ${CURDIR}/../models/face.cvimodel
    ${stats}=    Run Inference    duration=30
    Should Be True
    ...    ${stats.fps.avg} >= 15
    ...    msg=avg fps ${stats.fps.avg} below 15 fps floor

*** Test Cases ***
Multi-Model FPS Sweep
    [Tags]    regression
    [Template]    Model Should Meet FPS Floor
    ${CURDIR}/../models/face.cvimodel        15
    ${CURDIR}/../models/person.cvimodel      12
    ${CURDIR}/../models/vehicle.cvimodel     10
