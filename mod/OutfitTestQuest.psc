Scriptname OutfitTestQuest extends Quest

Cell Property TestCell Auto Const
Weapon Property TestPistol Auto Const
Ammo Property TestAmmo Auto Const
Action Property SheatheAction Auto Const
Action Property AimAction Auto Const
Action Property ReleaseAimAction Auto Const
Action Property FireAction Auto Const
Action Property ReloadAction Auto Const

bool running
bool aimRequested
bool eventReceived
string expectedEvent
string lastStatus = "IDLE"
bool watching
bool readyReported
bool automatedDone
string crossingPhase
float crossingY
bool crossingSouth
bool crossed
int crossingTicks

Event OnInit()
    WatchForRun()
EndEvent

Event OnQuestInit()
    WatchForRun()
EndEvent

Function WatchForRun()
    if !watching && OutfitTestCamera.AutomationState() > 0
        watching = true
        StartTimer(0.5, 1)
    endif
EndFunction

Event OnTimer(int timerID)
    if timerID == 2
        CheckCrossing()
        return
    endif
    if timerID != 1
        return
    endif
    int control = OutfitTestCamera.AutomationState()
    if control == 3
        Debug.QuitGame()
        return
    endif
    if !automatedDone && TestAreaReady(Game.GetPlayer())
        if !readyReported
            readyReported = true
            OutfitTestCamera.Report("LOAD_READY")
        endif
        if control == 2
            automatedDone = true
            int scenario = OutfitTestCamera.Scenario()
            int camera = OutfitTestCamera.CameraOverride()
            RunScenario(OutfitTestCamera.OutfitPlugin(), OutfitTestCamera.OutfitForm(), scenario, camera)
        endif
    endif
    StartTimer(0.5, 1)
EndEvent

Function RunScenario(string pluginName, int localFormID, int scenario, int camera)
    if running
        return
    endif
    running = true
    Mark("PREPARING " + pluginName + " " + localFormID)
    Actor player = Game.GetPlayer()
    Armor primary = Game.GetFormFromFile(localFormID, pluginName) as Armor
    string problem = Prepare(player, primary)
    if problem == "" && OutfitTestCamera.ExtraPieceCount() > 0
        problem = EquipExtraPieces(player, primary)
    endif
    if problem == ""
        if scenario == 0
            problem = RecordPistol(player, camera)
        elseif scenario == 1
            problem = RecordStanding(player, camera)
        elseif scenario == 2
            problem = RecordLocomotion(player, camera)
        elseif scenario == 3
            problem = RecordPosture(player, camera)
        elseif scenario == 4
            problem = RecordFirstPerson(player)
        elseif scenario == 5
            problem = RecordWorkbench(player)
        elseif scenario == 6
            problem = RecordRifle(player, camera)
        elseif scenario == 7
            problem = RecordSprintJump(player)
        else
            problem = "Unknown scenario."
        endif
    endif
    crossingPhase = ""
    CancelTimer(2)
    Game.SetPlayerAIDriven(false)
    if aimRequested && TestAreaReady(player)
        player.PlayIdleAction(ReleaseAimAction, None)
    endif
    aimRequested = false
    StopCamera()
    if problem == ""
        Mark("COMPLETE")
    else
        Mark("FAILED " + problem)
    endif
    Status()
    running = false
EndFunction

string Function EquipExtraPieces(Actor player, Armor primary)
    int count = OutfitTestCamera.ExtraPieceCount()
    Armor[] equipped = new Armor[count + 1]
    equipped[0] = primary
    int index = 0
    while index < count
        string plugin = OutfitTestCamera.ExtraPiecePlugin(index)
        int formID = OutfitTestCamera.ExtraPieceForm(index)
        Armor piece = Game.GetFormFromFile(formID, plugin) as Armor
        if piece == None
            return "Armor form missing: " + plugin + " " + formID
        endif
        if !EquipPiece(player, piece)
            return "The game did not equip " + plugin + " " + formID
        endif
        equipped[index + 1] = piece
        index += 1
    endwhile
    Utility.Wait(0.75)
    index = 0
    while index < equipped.Length
        if !player.IsEquipped(equipped[index])
            return "A later piece replaced an equipped piece: " + equipped[index]
        endif
        index += 1
    endwhile
    Mark("OUTFIT_EQUIPPED " + equipped.Length)
    return ""
EndFunction

bool Function EquipPiece(Actor player, Armor piece)
    if player.GetItemCount(piece) == 0
        player.AddItem(piece, 1, true)
    endif
    int attempts = 2
    while !player.IsEquipped(piece) && attempts > 0
        player.EquipItem(piece, false, true)
        int remaining = 20
        while !player.IsEquipped(piece) && remaining > 0
            Utility.Wait(0.1)
            remaining -= 1
        endwhile
        attempts -= 1
    endwhile
    return player.IsEquipped(piece)
EndFunction

bool Function StartCamera(Actor player, int preset, float offsetY = 0.0, float heading = -1.0)
    if !TestAreaReady(player)
        return false
    endif
    if heading < 0.0
        heading = player.GetAngleZ()
    endif
    if !OutfitTestCamera.BeginPreset(preset, player.GetPositionX(), player.GetPositionY() + offsetY, player.GetPositionZ(), heading)
        return false
    endif
    if !WaitForWristCamera()
        return false
    endif
    Mark("VIEW " + OutfitTestCamera.PresetName(preset))
    Utility.Wait(0.35)
    return true
EndFunction

bool Function StopCamera()
    if OutfitTestCamera.Status() == 0
        return true
    endif
    OutfitTestCamera.EndShot()
    int remaining = 20
    while OutfitTestCamera.Status() != 0 && remaining > 0
        Utility.WaitMenuMode(0.1)
        remaining -= 1
    endwhile
    return OutfitTestCamera.Status() == 0
EndFunction

string Function RecordPistol(Actor player, int camera)
    int[] presets = new int[2]
    presets[0] = 0
    presets[1] = 1
    return RecordPistolViews(player, presets, camera)
EndFunction

string Function RecordRifle(Actor player, int camera)
    Weapon rifle = Game.GetFormFromFile(0x000DF42E, "Fallout4.esm") as Weapon
    Ammo rounds = Game.GetFormFromFile(0x0001F66A, "Fallout4.esm") as Ammo
    if rifle == None || rounds == None
        return "Combat rifle or .45 cartridges are missing."
    endif
    string problem = PrepareWeapon(player, rifle, rounds)
    if problem != ""
        return problem
    endif
    if camera < 0
        camera = 22
    endif
    if !StartCamera(player, camera)
        return "Rifle camera did not start."
    endif
    return PlayWeaponSequence(player, rifle, rounds)
EndFunction

string Function RecordSprintJump(Actor player)
    int forwardKey = Input.GetMappedKey("Forward", 0)
    int sprintKey = Input.GetMappedKey("Sprint", 0)
    int jumpKey = Input.GetMappedKey("Jump", 0)
    if forwardKey <= 0 || sprintKey <= 0 || jumpKey <= 0
        return "Bind Forward, Sprint and Jump to keyboard keys."
    endif
    ActorValue actionPoints = Game.GetFormFromFile(0x2D5, "Fallout4.esm") as ActorValue
    player.RestoreValue(actionPoints, 1000.0)
    if player.IsOverEncumbered()
        return "The reference character is carrying too much to sprint."
    endif
    Form marker = Game.GetFormFromFile(0x3B, "Fallout4.esm")
    ObjectReference start = player.PlaceAtMe(marker, 1, false, false, true)
    if start == None
        return "Could not place the sprint start."
    endif
    start.SetPosition(-1500.0, -1170.0, 0.0)
    player.MoveTo(start, 0.0, 0.0, 0.0, false)
    Utility.WaitMenuMode(1.0)
    if !WaitForMenu("LoadingMenu", false, 200)
        return "The sprint area did not finish loading."
    endif
    player.SetAngle(0.0, 0.0, 180.0)
    Game.ForceThirdPerson()
    Utility.Wait(1.8)
    Mark("MOTION_CAMERA")
    Utility.Wait(0.8)
    float ground = player.GetPositionZ()
    Mark("VIEW motion-chase")
    Mark("MOTION_START " + player.GetPositionX() + " " + player.GetPositionY())
    Mark("SPRINT_INPUT " + forwardKey + " " + sprintKey + " " + jumpKey)
    int remaining = 12
    while !player.IsSprinting() && remaining > 0
        Utility.Wait(0.08)
        remaining -= 1
    endwhile
    if !player.IsSprinting()
        Action sprint = Game.GetFormFromFile(0x3B4A7, "Fallout4.esm") as Action
        player.PlayIdleAction(sprint, None)
        remaining = 8
        while !player.IsSprinting() && remaining > 0
            Utility.Wait(0.08)
            remaining -= 1
        endwhile
    endif
    bool sprinted = player.IsSprinting()
    if sprinted
        Mark("SPRINT")
        Utility.Wait(0.3)
    endif
    Mark("JUMP_INPUT")
    remaining = 30
    while player.GetPositionZ() < ground + 22.0 && remaining > 0
        Utility.Wait(0.06)
        remaining -= 1
    endwhile
    if remaining == 0
        return "The player did not leave the ground."
    endif
    Mark("JUMP")
    float previousZ = player.GetPositionZ()
    float peakZ = previousZ
    int stableTicks = 0
    remaining = 45
    while stableTicks < 3 && remaining > 0
        Utility.Wait(0.07)
        float currentZ = player.GetPositionZ()
        if currentZ > peakZ
            peakZ = currentZ
        endif
        float deltaZ = currentZ - previousZ
        if currentZ < peakZ - 12.0 && deltaZ > -1.0 && deltaZ < 1.0
            stableTicks += 1
        else
            stableTicks = 0
        endif
        previousZ = currentZ
        remaining -= 1
    endwhile
    if stableTicks < 3
        return "The player did not land."
    endif
    Mark("LANDING")
    Mark("MOTION_END " + player.GetPositionX() + " " + player.GetPositionY() + " " + player.GetPositionZ())
    Utility.Wait(1.3)
    if !sprinted
        return "Jump and landing completed, but the game did not confirm sprinting."
    endif
    return ""
EndFunction

string Function RecordPistolViews(Actor player, int[] presets, int camera)
    int count = presets.Length
    if camera >= 0
        presets[0] = camera
        count = 1
    endif
    int index = 0
    while index < count
        if !StartCamera(player, presets[index])
            return "Pistol camera did not start."
        endif
        string problem = PlayPistolSequence(player)
        if problem != ""
            return problem
        endif
        if OutfitTestCamera.Status() != 2 || !StopCamera()
            return "Pistol camera was interrupted."
        endif
        index += 1
    endwhile
    return ""
EndFunction

string Function RecordStanding(Actor player, int camera)
    int[] presets = new int[4]
    presets[0] = 2
    presets[1] = 3
    presets[2] = 4
    presets[3] = 5
    int count = presets.Length
    if camera >= 0
        presets[0] = camera
        count = 1
    endif
    int index = 0
    while index < count
        if !StartCamera(player, presets[index])
            return "Standing camera did not start."
        endif
        Mark("STANDING")
        Utility.Wait(1.8)
        if OutfitTestCamera.Status() != 2 || !StopCamera()
            return "Standing camera was interrupted."
        endif
        index += 1
    endwhile
    return ""
EndFunction

string Function RecordLocomotion(Actor player, int camera)
    Form marker = Game.GetFormFromFile(0x3B, "Fallout4.esm")
    ObjectReference pointA = player.PlaceAtMe(marker, 1, false, false, true)
    ObjectReference pointB = player.PlaceAtMe(marker, 1, false, false, true)
    if pointA == None || pointB == None
        return "Route markers could not be placed."
    endif
    pointA.SetPosition(-1792.0, -1344.0, 0.0)
    pointB.SetPosition(-1792.0, -1690.0, 0.0)
    player.MoveTo(pointA, 0.0, 0.0, 0.0, false)
    player.SetAngle(0.0, 0.0, 180.0)
    Utility.Wait(1.0)
    int[] presets = new int[2]
    presets[0] = 7
    presets[1] = 8
    int count = presets.Length
    if camera >= 0
        presets[0] = camera
        count = 1
    endif
    int index = 0
    while index < count
        if !StartCamera(player, presets[index], -173.0, 180.0)
            return "Route camera did not start."
        endif
        if !Travel(player, pointB, 0.45, "WALK", true)
            return "Walk did not reach point B."
        endif
        TurnAtEnd(player)
        ResetRoute(player, pointA)
        if !Travel(player, pointB, 1.0, "RUN", true)
            return "Run did not reach point B."
        endif
        Mark("ROUTE_STOP")
        Utility.Wait(1.6)
        ResetRoute(player, pointA)
        player.StartSneaking()
        if !WaitForSneak(player, true) || !Travel(player, pointB, 0.45, "CROUCH_WALK", true)
            return "Crouched walk did not reach point B."
        endif
        Action sneak = Game.GetFormFromFile(0x13007, "Fallout4.esm") as Action
        player.PlayIdleAction(sneak, None)
        if !WaitForSneak(player, false)
            return "The player did not stand up after the route."
        endif
        if OutfitTestCamera.Status() != 2 || !StopCamera()
            return "Route camera was interrupted."
        endif
        ResetRoute(player, pointA)
        index += 1
    endwhile
    return ""
EndFunction

Function TurnAtEnd(Actor player)
    Mark("TURN_START")
    Action turn = Game.GetFormFromFile(0x959FD, "Fallout4.esm") as Action
    player.PlayIdleAction(turn, None)
    float heading = player.GetAngleZ()
    int step = 1
    while step <= 6
        player.SetAngle(0.0, 0.0, heading + step * 30.0)
        if step == 3
            Mark("TURN")
        endif
        Utility.Wait(0.12)
        step += 1
    endwhile
    Utility.Wait(0.4)
EndFunction

Function ResetRoute(Actor player, ObjectReference start)
    Mark("RESET_ROUTE")
    player.MoveTo(start, 0.0, 0.0, 0.0, false)
    player.SetAngle(0.0, 0.0, 180.0)
    Utility.Wait(0.7)
EndFunction

bool Function Travel(Actor player, ObjectReference destination, float speed, string phase, bool south)
    crossed = false
    crossingTicks = 0
    crossingSouth = south
    crossingY = -1517.0
    crossingPhase = phase
    Mark(phase + "_START")
    Game.SetPlayerAIDriven(true)
    StartTimer(0.1, 2)
    bool reached = player.PathToReference(destination, speed)
    Game.SetPlayerAIDriven(false)
    crossingPhase = ""
    CancelTimer(2)
    return (reached || player.GetDistance(destination) < 70.0) && crossed
EndFunction

Function CheckCrossing()
    if crossingPhase == ""
        return
    endif
    Actor player = Game.GetPlayer()
    float positionY = player.GetPositionY()
    if !crossed && ((crossingSouth && positionY <= crossingY) || (!crossingSouth && positionY >= crossingY))
        if crossingPhase == "CROUCH_WALK" && !player.IsSneaking()
            Mark("ROUTE_TIMEOUT Sneak stance lost at the capture point.")
            Game.SetPlayerAIDriven(false)
            return
        endif
        crossed = true
        Mark(crossingPhase)
    endif
    crossingTicks += 1
    if crossingTicks >= 180
        Mark("ROUTE_TIMEOUT " + crossingPhase + " at Y=" + positionY)
        Game.SetPlayerAIDriven(false)
    else
        StartTimer(0.1, 2)
    endif
EndFunction

bool Function WaitForSneak(Actor player, bool sneaking)
    int remaining = 35
    while player.IsSneaking() != sneaking && remaining > 0
        Utility.Wait(0.1)
        remaining -= 1
    endwhile
    return player.IsSneaking() == sneaking
EndFunction

bool Function WaitForSit(Actor player, int expected)
    int remaining = 65
    while player.GetSitState() != expected && remaining > 0
        Utility.Wait(0.1)
        remaining -= 1
    endwhile
    return player.GetSitState() == expected
EndFunction

string Function RecordPosture(Actor player, int camera)
    if camera < 0
        camera = 6
    endif
    if !StartCamera(player, camera)
        return "Posture camera did not start."
    endif
    Action sneak = Game.GetFormFromFile(0x13007, "Fallout4.esm") as Action
    player.StartSneaking()
    if !WaitForSneak(player, true)
        return "The player did not crouch."
    endif
    Mark("CROUCHED")
    Utility.Wait(2.0)
    player.PlayIdleAction(sneak, None)
    if !WaitForSneak(player, false)
        return "The player did not stand up from crouch."
    endif
    Mark("STOOD_UP")
    Utility.Wait(1.7)
    if !StopCamera()
        return "Posture camera could not be restored."
    endif
    Form chairBase = Game.GetFormFromFile(0xE37D3, "Fallout4.esm")
    ObjectReference chair = player.PlaceAtMe(chairBase, 1, false, false, true)
    if chair == None
        return "The test chair could not be placed."
    endif
    chair.SetPosition(-1792.0, -1440.0, 0.0)
    chair.SetAngle(0.0, 0.0, 0.0)
    player.SetPosition(-1792.0, -1370.0, 0.0)
    player.SetAngle(0.0, 0.0, 180.0)
    Utility.Wait(0.6)
    chair.Activate(player, false)
    if !WaitForSit(player, 3)
        return "The player did not sit."
    endif
    if !StartCamera(player, camera)
        return "Seated camera did not start."
    endif
    Mark("SEATED")
    Utility.Wait(2.0)
    Action exitSeat = Game.GetFormFromFile(0x2248D, "Fallout4.esm") as Action
    player.PlayIdleAction(exitSeat, None)
    if !WaitForSit(player, 0)
        return "The player did not get up from the chair."
    endif
    Mark("GOT_UP")
    Utility.Wait(1.8)
    return ""
EndFunction

bool Function WaitForMenu(string menu, bool opened, int remaining = 50)
    while UI.IsMenuOpen(menu) != opened && remaining > 0
        Utility.WaitMenuMode(0.1)
        remaining -= 1
    endwhile
    return UI.IsMenuOpen(menu) == opened
EndFunction

string Function RecordFirstPerson(Actor player)
    Game.ForceFirstPerson()
    Utility.Wait(0.75)
    if Game.GetCameraState() != 0
        return "First-person camera was not active."
    endif
    Mark("VIEW first-person")
    string problem = PlayPistolSequence(player)
    if problem != ""
        return problem
    endif
    OutfitTestCamera.SetPipboy(true)
    if !WaitForMenu("PipboyMenu", true)
        return "The Pip-Boy menu did not open."
    endif
    Mark("PIPBOY")
    Utility.WaitMenuMode(2.4)
    OutfitTestCamera.SetPipboy(false)
    if !WaitForMenu("PipboyMenu", false)
        return "The Pip-Boy menu did not close."
    endif
    return ""
EndFunction

string Function RecordWorkbench(Actor player)
    ObjectReference bench = Game.GetFormFromFile(0x1E7DBB, "Fallout4.esm") as ObjectReference
    if bench == None || bench.GetParentCell() != TestCell
        return "The QASmoke weapons workbench is missing."
    endif
    player.MoveTo(bench, -96.0, 0.0, 0.0, false)
    Utility.WaitMenuMode(1.0)
    if !WaitForMenu("LoadingMenu", false, 200)
        return "The weapons workbench area did not finish loading."
    endif
    player.SetAngle(0.0, 0.0, 90.0)
    Game.ForceThirdPerson()
    Utility.Wait(1.0)
    Mark("VIEW workbench")
    Mark("BENCH_APPROACH")
    Utility.Wait(1.3)
    bench.Activate(player, false)
    if !WaitForMenu("ExamineMenu", true)
        return "The weapons workbench menu did not open."
    endif
    Mark("WORKBENCH")
    Utility.WaitMenuMode(2.0)
    UI.CloseMenu("ExamineMenu")
    if !WaitForMenu("ExamineMenu", false)
        return "The weapons workbench menu did not close."
    endif
    return ""
EndFunction

Function Status()
    Debug.Notification("Outfit test: " + lastStatus)
EndFunction

bool Function WaitForWristCamera()
    int remaining = 20
    while OutfitTestCamera.Status() == 1 && remaining > 0
        Utility.Wait(0.1)
        remaining -= 1
    endwhile
    return OutfitTestCamera.Status() == 2
EndFunction

string Function Prepare(Actor player, Armor outfitPiece)
    if !TestAreaReady(player)
        return "Load the QASmoke reference save."
    endif
    if player.IsSneaking() || player.IsInPowerArmor()
        return "Stand up and exit power armor."
    endif
    if outfitPiece == None
        return "Armor form missing. Check the plugin and local FormID."
    endif

    if !EquipPiece(player, outfitPiece)
        return "The selected armor did not equip."
    endif
    Game.ForceThirdPerson()
    Utility.Wait(0.75)
    Mark("ARMOR_EQUIPPED")
    return ""
EndFunction

string Function PlayPistolSequence(Actor player)
    return PlayWeaponSequence(player, TestPistol, TestAmmo)
EndFunction

string Function PlayWeaponSequence(Actor player, Weapon weaponToTest, Ammo testRounds)
    string problem = PrepareWeapon(player, weaponToTest, testRounds)
    if problem != ""
        return problem
    endif
    Mark("REST")
    Utility.Wait(3.0)
    if !TestAreaReady(player)
        return "The test left QASmoke."
    endif
    player.DrawWeapon()
    if !WaitForWeaponState(player, true)
        return "The weapon did not draw."
    endif
    Mark("DRAWN")
    Utility.Wait(1.0)

    aimRequested = true
    problem = PlayActionAndCheckEvent(player, weaponToTest, AimAction, "sightedStateEnter", 3.0)
    if problem != ""
        return problem
    endif
    Mark("AIMING")
    Utility.Wait(3.0)

    Mark("FIRING")
    problem = PlayActionAndCheckEvent(player, weaponToTest, FireAction, "weaponFire", 3.0)
    if problem != ""
        return problem
    endif
    if !player.PlayIdleAction(ReleaseAimAction, None)
        return "The game refused to release aim."
    endif
    aimRequested = false
    Utility.Wait(1.0)

    Mark("RELOADING")
    problem = PlayActionAndCheckEvent(player, weaponToTest, ReloadAction, "reloadComplete", 6.0)
    if problem != ""
        return problem
    endif
    Mark("RELOADED")
    Utility.Wait(1.5)
    player.PlayIdleAction(SheatheAction, None)
    if !WaitForWeaponState(player, false)
        return "The weapon did not return to its holster."
    endif
    Mark("REST_AFTER_RELOAD")
    Utility.Wait(2.0)
    return ""
EndFunction

string Function PrepareWeapon(Actor player, Weapon weaponToTest, Ammo testRounds)
    if player.IsWeaponDrawn()
        player.PlayIdleAction(SheatheAction, None)
        if !WaitForWeaponState(player, false)
            return "The weapon did not holster."
        endif
    endif

    if player.GetItemCount(weaponToTest) == 0
        player.AddItem(weaponToTest, 1, true)
    endif
    int roundsToAdd = 48 - player.GetItemCount(testRounds)
    if roundsToAdd > 0
        player.AddItem(testRounds, roundsToAdd, true)
    endif
    if player.GetEquippedWeapon(0) != weaponToTest
        player.EquipItem(weaponToTest, false, true)
        int remaining = 20
        while player.GetEquippedWeapon(0) != weaponToTest && remaining > 0
            Utility.Wait(0.15)
            remaining -= 1
        endwhile
        if player.GetEquippedWeapon(0) != weaponToTest
            return "Could not equip the selected weapon."
        endif
    endif
    if player.IsWeaponDrawn()
        player.PlayIdleAction(SheatheAction, None)
        if !WaitForWeaponState(player, false)
            return "The newly equipped weapon did not holster."
        endif
    endif
    return ""
EndFunction

bool Function TestAreaReady(Actor player)
    return TestCell != None && player != None && player.GetParentCell() == TestCell && player.Is3DLoaded()
EndFunction

bool Function WaitForWeaponState(Actor player, bool drawn)
    int remaining = 30
    while remaining > 0 && TestAreaReady(player)
        if player.IsWeaponDrawn() == drawn
            return true
        endif
        Utility.Wait(0.1)
        remaining -= 1
    endwhile
    return false
EndFunction

string Function PlayActionAndCheckEvent(Actor player, Weapon weaponToTest, Action animationAction, string eventName, float timeout)
    if !TestAreaReady(player) || player.GetEquippedWeapon(0) != weaponToTest || !player.IsWeaponDrawn()
        return "The player or weapon is no longer ready for " + eventName + "."
    endif
    eventReceived = false
    expectedEvent = eventName
    if !RegisterForAnimationEvent(player, eventName)
        expectedEvent = ""
        return "Could not listen for " + eventName + "."
    endif

    string problem = ""
    if player.PlayIdleAction(animationAction, None)
        int remaining = (timeout * 10.0) as int
        while !eventReceived && remaining > 0 && TestAreaReady(player)
            Utility.Wait(0.1)
            remaining -= 1
        endwhile
        if !eventReceived
            problem = "Animation event timed out: " + eventName + "."
        endif
    else
        problem = "The game refused the action for " + eventName + "."
    endif

    UnregisterForAnimationEvent(player, eventName)
    expectedEvent = ""
    return problem
EndFunction

Event OnAnimationEvent(ObjectReference sender, string eventName)
    if running && sender == Game.GetPlayer() && eventName == expectedEvent
        eventReceived = true
        Debug.Trace("[Outfit Test] EVENT " + eventName, 0)
    endif
EndEvent

Function Mark(string phase)
    lastStatus = phase
    Debug.Trace("[Outfit Test] " + phase, 0)
    if watching
        OutfitTestCamera.Report(phase)
    endif
EndFunction
