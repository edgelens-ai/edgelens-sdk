*** Settings ***
Library           EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}    scope=TEST

*** Test Cases ***
Custom Binary Runs Clean
    [Tags]    regression
    Open Session    device_type=recamera-2002    os=recamagined
    Wait Ready
    # Deploy lands files in /userdata/Models/ on reCamaginedOS; run from there.
    @{extra}=    Create List    ${CURDIR}/../models/face.cvimodel
    Deploy Model    ${CURDIR}/../build/my_inference    files=${extra}
    ${r}=    Exec    /userdata/Models/my_inference --model /userdata/Models/face.cvimodel --duration 5
    Should Be Equal As Integers    ${r.exit_code}    0
    Should Not Contain    ${r.stdout}    ERROR
    [Teardown]    Release Session
