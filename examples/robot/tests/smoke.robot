*** Settings ***
Library           EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=TEST

*** Test Cases ***
Device Info Populated
    [Tags]    smoke
    Open Session    device_type=recamera-2002    os=stock-os
    Wait Ready
    ${info}=    Device Info
    Should Not Be Empty    ${info.hostname}
    Should Be Equal    ${info.hardware.cpu_arch}    riscv64
    [Teardown]    Release Session
