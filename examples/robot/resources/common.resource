*** Settings ***
Library    EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=SUITE
Documentation    Shared keywords for the EdgeLens robot examples.

*** Keywords ***
Model Should Meet FPS Floor
    [Arguments]    ${model}    ${min_fps}    ${duration}=20
    Deploy Model    ${model}
    ${stats}=    Run Inference    duration=${duration}
    Should Be True
    ...    ${stats.fps.avg} >= ${min_fps}
    ...    msg=avg fps ${stats.fps.avg} below ${min_fps} floor
    [Return]    ${stats}
