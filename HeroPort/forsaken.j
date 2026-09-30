// Personal 1.24e compatibility experiment, based on retail 3.0.0.24268 data.
// Healing modifiers sample net HP gain; simultaneous damage/overheal cannot be
// reconstructed by the old engine. Do not describe this as an exact native port.
globals
    hashtable FP_data = InitHashtable()
    group FP_heroes = CreateGroup()
    group FP_units = CreateGroup()
    real FP_clock = 0.0
    integer FP_cycle = 0
endglobals

function FP_Alive takes unit u returns boolean
    return u != null and GetUnitTypeId(u) != 0 and GetWidgetLife(u) > 0.405 and not IsUnitType(u, UNIT_TYPE_DEAD)
endfunction

function FP_Heal takes unit u, real amount returns nothing
    local integer id = GetHandleId(u)
    local real factor = LoadReal(FP_data, id, 11)
    if factor <= 0.0 then
        set factor = 1.0
    endif
    if FP_Alive(u) then
        call SetWidgetLife(u, RMinBJ(GetUnitState(u, UNIT_STATE_MAX_LIFE), GetWidgetLife(u) + amount * factor))
        call SaveReal(FP_data, id, 10, GetWidgetLife(u))
    endif
endfunction

function FP_Dummy takes unit source, unit target, integer spellId, integer level, string order returns nothing
    local unit d = CreateUnit(GetOwningPlayer(source), 'fPdm', GetUnitX(target), GetUnitY(target), 0.0)
    call UnitAddAbility(d, spellId)
    call SetUnitAbilityLevel(d, spellId, level)
    call IssueTargetOrder(d, order, target)
    call UnitApplyTimedLife(d, 'BTLF', 2.0)
    set d = null
endfunction

function FP_Sound takes string path, unit u returns nothing
    local sound s = CreateSound(path, false, true, true, 10, 10, "DefaultEAXON")
    call SetSoundPosition(s, GetUnitX(u), GetUnitY(u), 60.0)
    call SetSoundDistances(s, 400.0, 2200.0)
    call SetSoundDistanceCutoff(s, 2200.0)
    call SetSoundVolume(s, 100)
    call StartSound(s)
    call KillSoundWhenDone(s)
    set s = null
endfunction

function FP_DashTick takes nothing returns nothing
    local timer t = GetExpiredTimer()
    local integer id = GetHandleId(t)
    local unit u = LoadUnitHandle(FP_data, id, 0)
    local group hit = LoadGroupHandle(FP_data, id, 4)
    local group near = CreateGroup()
    local unit v
    local real remaining = LoadReal(FP_data, id, 1)
    local real step = RMinBJ(30.0, remaining)
    local real x = GetUnitX(u) + LoadReal(FP_data, id, 2) * step
    local real y = GetUnitY(u) + LoadReal(FP_data, id, 3) * step
    local integer level = LoadInteger(FP_data, id, 6)
    if FP_Alive(u) and remaining > 0.0 and not IsTerrainPathable(x, y, PATHING_TYPE_WALKABILITY) then
        call SetUnitPosition(u, x, y)
        if SquareRoot((GetUnitX(u)-x)*(GetUnitX(u)-x)+(GetUnitY(u)-y)*(GetUnitY(u)-y)) > 48.0 then
            set remaining = 0.0
        else
            set remaining = remaining - step
        endif
        call GroupEnumUnitsInRange(near, GetUnitX(u), GetUnitY(u), 100.0, null)
        loop
            set v = FirstOfGroup(near)
            exitwhen v == null
            call GroupRemoveUnit(near, v)
            if FP_Alive(v) and IsUnitEnemy(v, GetOwningPlayer(u)) and not IsUnitInGroup(v, hit) and not IsUnitType(v, UNIT_TYPE_FLYING) and not IsUnitType(v, UNIT_TYPE_STRUCTURE) and not IsUnitType(v, UNIT_TYPE_MAGIC_IMMUNE) then
                call GroupAddUnit(hit, v)
                call UnitDamageTarget(u, v, 50.0 + 50.0*level, false, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, WEAPON_TYPE_WHOKNOWS)
                call FP_Dummy(u, v, 'Afsl', level, "cripple")
            endif
        endloop
    else
        set remaining = 0.0
    endif
    call DestroyGroup(near)
    if remaining <= 0.0 then
        call PauseUnit(u, false)
        call SetUnitTimeScale(u, 1.0)
        call SetUnitAnimation(u, "stand")
        call DestroyEffect(LoadEffectHandle(FP_data, id, 5))
        call DestroyGroup(hit)
        call FlushChildHashtable(FP_data, id)
        call DestroyTimer(t)
    else
        call SaveReal(FP_data, id, 1, remaining)
    endif
    set near = null
    set hit = null
    set u = null
    set v = null
    set t = null
endfunction

function FP_Dash takes unit u, real x, real y returns nothing
    local timer t = CreateTimer()
    local integer id = GetHandleId(t)
    local real dx = x - GetUnitX(u)
    local real dy = y - GetUnitY(u)
    local real distance = SquareRoot(dx*dx+dy*dy)
    if distance < 1.0 then
        call DestroyTimer(t)
    else
        call SaveUnitHandle(FP_data, id, 0, u)
        call SaveReal(FP_data, id, 1, RMinBJ(distance, 725.0))
        call SaveReal(FP_data, id, 2, dx/distance)
        call SaveReal(FP_data, id, 3, dy/distance)
        call SaveGroupHandle(FP_data, id, 4, CreateGroup())
        call SaveEffectHandle(FP_data, id, 5, AddSpecialEffectTarget("Abilities\\Spells\\Other\\RighteousFury\\RighteousFury.mdx", u, "origin"))
        call SaveInteger(FP_data, id, 6, GetUnitAbilityLevel(u, 'ANcp'))
        call SetUnitFacing(u, Atan2(dy, dx)*bj_RADTODEG)
        call PauseUnit(u, true)
        call SetUnitAnimation(u, "walk")
        call SetUnitTimeScale(u, 2.0)
        call FP_Sound("Abilities\\Spells\\Other\\RighteousFury\\RighteousFury.wav", u)
        call TimerStart(t, 0.03, true, function FP_DashTick)
    endif
    set t = null
endfunction

function FP_ConsecrationTick takes nothing returns nothing
    local timer t = GetExpiredTimer()
    local integer id = GetHandleId(t)
    local unit u = LoadUnitHandle(FP_data, id, 0)
    local integer level = LoadInteger(FP_data, id, 4)
    local real remaining = LoadReal(FP_data, id, 3)
    local real healing = 25.0
    local real reduction = 0.25
    local group near = CreateGroup()
    local unit v
    local integer vid
    if level == 2 then
        set healing = 35.0
        set reduction = 0.33
    elseif level == 3 then
        set healing = 50.0
        set reduction = 0.50
    endif
    if remaining > 0.0 then
        call GroupEnumUnitsInRange(near, LoadReal(FP_data, id, 1), LoadReal(FP_data, id, 2), 300.0, null)
        loop
            set v = FirstOfGroup(near)
            exitwhen v == null
            call GroupRemoveUnit(near, v)
            if FP_Alive(v) and not IsUnitType(v, UNIT_TYPE_STRUCTURE) and not IsUnitType(v, UNIT_TYPE_FLYING) and not IsUnitType(v, UNIT_TYPE_MECHANICAL) then
                if IsUnitAlly(v, GetOwningPlayer(u)) and not IsUnitType(v, UNIT_TYPE_UNDEAD) then
                    call FP_Heal(v, healing*0.25)
                elseif IsUnitEnemy(v, GetOwningPlayer(u)) and IsUnitType(v, UNIT_TYPE_UNDEAD) and not IsUnitType(v, UNIT_TYPE_MAGIC_IMMUNE) then
                    call UnitDamageTarget(u, v, (10.0+10.0*level)*0.25, false, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, WEAPON_TYPE_WHOKNOWS)
                    set vid = GetHandleId(v)
                    if LoadReal(FP_data, vid, 21) < FP_clock or LoadReal(FP_data, vid, 20) < reduction then
                        call SaveReal(FP_data, vid, 20, reduction)
                    endif
                    call SaveReal(FP_data, vid, 21, FP_clock+0.35)
                endif
            endif
        endloop
    endif
    call DestroyGroup(near)
    set remaining = remaining - 0.25
    if remaining <= 0.0 then
        call DestroyEffect(LoadEffectHandle(FP_data, id, 5))
        call FlushChildHashtable(FP_data, id)
        call DestroyTimer(t)
    else
        call SaveReal(FP_data, id, 3, remaining)
    endif
    set near = null
    set t = null
    set u = null
    set v = null
endfunction

function FP_Consecration takes unit u returns nothing
    local timer t = CreateTimer()
    local integer id = GetHandleId(t)
    call SaveUnitHandle(FP_data, id, 0, u)
    call SaveReal(FP_data, id, 1, GetUnitX(u))
    call SaveReal(FP_data, id, 2, GetUnitY(u))
    call SaveReal(FP_data, id, 3, 5.0)
    call SaveInteger(FP_data, id, 4, GetUnitAbilityLevel(u, 'AHcr'))
    call SaveEffectHandle(FP_data, id, 5, AddSpecialEffect("Abilities\\Spells\\Other\\Consecration\\Consecration.mdx", GetUnitX(u), GetUnitY(u)))
    call FP_Sound("Abilities\\Spells\\Other\\Consecration\\Consecration.wav", u)
    call TimerStart(t, 0.25, true, function FP_ConsecrationTick)
    set t = null
endfunction

function FP_Cleansing takes unit u returns nothing
    local group near = CreateGroup()
    local unit v
    local integer count
    call DestroyEffect(AddSpecialEffectTarget("Abilities\\Spells\\Other\\CleansingFire\\CleansingFireCaster.mdx", u, "origin"))
    call FP_Sound("Abilities\\Spells\\Other\\CleansingFire\\CleansingFire.wav", u)
    call GroupEnumUnitsInRange(near, GetUnitX(u), GetUnitY(u), 500.0, null)
    loop
        set v = FirstOfGroup(near)
        exitwhen v == null
        call GroupRemoveUnit(near, v)
        if FP_Alive(v) and not IsUnitType(v, UNIT_TYPE_STRUCTURE) then
            if IsUnitAlly(v, GetOwningPlayer(u)) then
                set count = UnitCountBuffsEx(v, false, true, true, false, false, false, false)
                call UnitRemoveBuffsEx(v, false, true, true, false, false, false, false)
                call FP_Heal(v, 125.0+50.0*count)
                call FP_Dummy(u, v, 'Afbn', IMinBJ(count+1, 20), "innerfire")
                call DestroyEffect(AddSpecialEffectTarget("Abilities\\Spells\\Other\\CleansingFire\\CleansingFireTarget.mdx", v, "origin"))
            elseif IsUnitEnemy(v, GetOwningPlayer(u)) and not IsUnitType(v, UNIT_TYPE_MAGIC_IMMUNE) then
                call UnitRemoveBuffsEx(v, true, false, true, false, false, false, false)
                if IsUnitType(v, UNIT_TYPE_SUMMONED) then
                    call UnitDamageTarget(u, v, 400.0, false, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, WEAPON_TYPE_WHOKNOWS)
                endif
                call FP_Dummy(u, v, 'Afst', 1, "thunderbolt")
            endif
        endif
    endloop
    call DestroyGroup(near)
    set near = null
    set v = null
endfunction

function FP_Cast takes nothing returns nothing
    local unit u = GetTriggerUnit()
    local integer spellId = GetSpellAbilityId()
    if GetUnitTypeId(u) == 'Npal' then
        if spellId == 'ANcp' then
            call FP_Dash(u, GetSpellTargetX(), GetSpellTargetY())
        elseif spellId == 'AHcr' then
            call FP_Consecration(u)
        elseif spellId == 'AHcl' then
            call FP_Cleansing(u)
        endif
    endif
    set u = null
endfunction

function FP_Ack takes unit u, string category, integer count returns nothing
    local integer id = GetHandleId(u)
    local integer index = ModuloInteger(LoadInteger(FP_data, id, 41), count)+1
    local sound s
    if FP_clock-LoadReal(FP_data, id, 40) >= 1.2 or not HaveSavedReal(FP_data, id, 40) then
        call SaveInteger(FP_data, id, 41, index)
        call SaveReal(FP_data, id, 40, FP_clock)
        set s = CreateSound("Units\\Creeps\\HeroForsakenPaladin\\FORSAKENPALADIN_"+category+I2S(index)+".wav", false, false, false, 10, 10, "HeroAcksEAX")
        call SetSoundVolume(s, 110)
        if GetLocalPlayer() == GetOwningPlayer(u) then
            call StartSound(s)
        endif
        call KillSoundWhenDone(s)
    endif
    set s = null
endfunction

function FP_Selected takes nothing returns nothing
    local unit u = GetTriggerUnit()
    local integer id = GetHandleId(u)
    local integer count = LoadInteger(FP_data, id, 42)+1
    if GetUnitTypeId(u) == 'Npal' and GetTriggerPlayer() == GetOwningPlayer(u) then
        call SaveInteger(FP_data, id, 42, count)
        if count > 5 then
            call FP_Ack(u, "Pissed", 4)
        else
            call FP_Ack(u, "What", 4)
        endif
    endif
    set u = null
endfunction

function FP_Ordered takes nothing returns nothing
    local unit u = GetTriggerUnit()
    if GetUnitTypeId(u) == 'Npal' and GetPlayerController(GetOwningPlayer(u)) == MAP_CONTROL_USER then
        call SaveInteger(FP_data, GetHandleId(u), 42, 0)
        if GetIssuedOrderId() == OrderId("attack") or GetIssuedOrderId() == OrderId("smart") and GetOrderTargetUnit() != null and IsUnitEnemy(GetOrderTargetUnit(), GetOwningPlayer(u)) then
            call FP_Ack(u, "Attack", 3)
        elseif GetIssuedOrderId() == OrderId("move") or GetIssuedOrderId() == OrderId("smart") or GetIssuedOrderId() == OrderId("patrol") then
            call FP_Ack(u, "Yes", 4)
        endif
    endif
    set u = null
endfunction

function FP_Sold takes nothing returns nothing
    local unit u = GetSoldUnit()
    if GetUnitTypeId(u) == 'Npal' then
        call FP_Ack(u, "Ready", 1)
    endif
    set u = null
endfunction

function FP_Died takes nothing returns nothing
    local unit u = GetTriggerUnit()
    if GetUnitTypeId(u) == 'Npal' then
        call FP_Sound("Units\\Creeps\\HeroForsakenPaladin\\FORSAKENPALADIN_Death1.wav", u)
    endif
    set u = null
endfunction

function FP_Collect takes nothing returns nothing
    local unit u = GetEnumUnit()
    local integer id = GetHandleId(u)
    // Scenario maps may create their neutral taverns after the initial timer.
    if GetUnitTypeId(u) == 'ntav' and GetOwningPlayer(u) == Player(PLAYER_NEUTRAL_PASSIVE) and FP_clock >= 135.0 and not LoadBoolean(FP_data, id, 40) then
        call AddUnitToStock(u, 'Npal', 1, 1)
        call SaveBoolean(FP_data, id, 40, true)
    endif
    if FP_Alive(u) and not IsUnitType(u, UNIT_TYPE_STRUCTURE) and GetUnitTypeId(u) != 'fPdm' then
        call GroupAddUnit(FP_units, u)
        call SaveInteger(FP_data, id, 12, 0)
        if not HaveSavedReal(FP_data, id, 10) then
            call SaveReal(FP_data, id, 10, GetWidgetLife(u))
        endif
        if GetUnitTypeId(u) == 'Npal' then
            call GroupAddUnit(FP_heroes, u)
        endif
    endif
    set u = null
endfunction

function FP_Aura takes nothing returns nothing
    local unit h = GetEnumUnit()
    local integer level = GetUnitAbilityLevel(h, 'AHpa')
    local group near
    local unit u
    local integer id
    if level > 0 and FP_Alive(h) then
        set near = CreateGroup()
        call GroupEnumUnitsInRange(near, GetUnitX(h), GetUnitY(h), 900.0, null)
        loop
            set u = FirstOfGroup(near)
            exitwhen u == null
            call GroupRemoveUnit(near, u)
            if FP_Alive(u) and IsUnitAlly(u, GetOwningPlayer(h)) and not IsUnitType(u, UNIT_TYPE_STRUCTURE) and GetUnitTypeId(u) != 'fPdm' then
                set id = GetHandleId(u)
                call SaveInteger(FP_data, id, 12, IMaxBJ(level, LoadInteger(FP_data, id, 12)))
            endif
        endloop
        call DestroyGroup(near)
    endif
    set near = null
    set h = null
    set u = null
endfunction

function FP_Health takes nothing returns nothing
    local unit u = GetEnumUnit()
    local integer id = GetHandleId(u)
    local integer level = LoadInteger(FP_data, id, 12)
    local real factor = 1.0
    local real life = GetWidgetLife(u)
    local real previous = LoadReal(FP_data, id, 10)
    local real oldFactor = LoadReal(FP_data, id, 11)
    if not FP_Alive(u) then
        call UnitRemoveAbility(u, 'Afmr')
        call FlushChildHashtable(FP_data, id)
        call GroupRemoveUnit(FP_units, u)
    else
        if oldFactor > 0.0 and oldFactor != 1.0 and life > previous and previous > 0.405 then
            call SetWidgetLife(u, RMinBJ(GetUnitState(u, UNIT_STATE_MAX_LIFE), previous+(life-previous)*oldFactor))
        endif
        if level > 0 then
            call UnitAddAbility(u, 'Afmr')
            call SetUnitAbilityLevel(u, 'Afmr', level)
            set factor = 1.10+0.05*level
        else
            call UnitRemoveAbility(u, 'Afmr')
        endif
        if LoadReal(FP_data, id, 21) > FP_clock then
            set factor = factor*(1.0-LoadReal(FP_data, id, 20))
        endif
        call SaveReal(FP_data, id, 11, factor)
        call SaveReal(FP_data, id, 10, GetWidgetLife(u))
    endif
    set u = null
endfunction

function FP_Update takes nothing returns nothing
    local group all
    set FP_clock = FP_clock + 0.1
    set FP_cycle = FP_cycle + 1
    if FP_cycle >= 5 then
        set FP_cycle = 0
        call GroupClear(FP_heroes)
        set all = CreateGroup()
        call GroupEnumUnitsInRect(all, bj_mapInitialPlayableArea, null)
        call ForGroup(all, function FP_Collect)
        call DestroyGroup(all)
        call ForGroup(FP_heroes, function FP_Aura)
    endif
    call ForGroup(FP_units, function FP_Health)
    set all = null
endfunction

function FP_Stock takes nothing returns nothing
    local unit u = GetEnumUnit()
    if GetUnitTypeId(u) == 'ntav' then
        call AddUnitToStock(u, 'Npal', 1, 1)
        call SaveBoolean(FP_data, GetHandleId(u), 40, true)
    endif
    set u = null
endfunction

function FP_OpenTaverns takes nothing returns nothing
    local group shops = CreateGroup()
    call DestroyTimer(GetExpiredTimer())
    call GroupEnumUnitsOfPlayer(shops, Player(PLAYER_NEUTRAL_PASSIVE), null)
    call ForGroup(shops, function FP_Stock)
    call DestroyGroup(shops)
    set shops = null
endfunction

function FP_Init takes nothing returns nothing
    local trigger casts = CreateTrigger()
    local trigger selected = CreateTrigger()
    local trigger orders = CreateTrigger()
    local trigger sold = CreateTrigger()
    local trigger deaths = CreateTrigger()
    local integer i = 0
    call DestroyTimer(GetExpiredTimer())
    loop
        exitwhen i >= 12
        call TriggerRegisterPlayerUnitEvent(casts, Player(i), EVENT_PLAYER_UNIT_SPELL_EFFECT, null)
        call TriggerRegisterPlayerUnitEvent(selected, Player(i), EVENT_PLAYER_UNIT_SELECTED, null)
        call TriggerRegisterPlayerUnitEvent(orders, Player(i), EVENT_PLAYER_UNIT_ISSUED_ORDER, null)
        call TriggerRegisterPlayerUnitEvent(orders, Player(i), EVENT_PLAYER_UNIT_ISSUED_POINT_ORDER, null)
        call TriggerRegisterPlayerUnitEvent(orders, Player(i), EVENT_PLAYER_UNIT_ISSUED_TARGET_ORDER, null)
        call TriggerRegisterPlayerUnitEvent(deaths, Player(i), EVENT_PLAYER_UNIT_DEATH, null)
        call SetPlayerTechMaxAllowed(Player(i), 'Npal', 1)
        set i = i + 1
    endloop
    call TriggerAddAction(casts, function FP_Cast)
    call TriggerAddAction(selected, function FP_Selected)
    call TriggerAddAction(orders, function FP_Ordered)
    call TriggerRegisterPlayerUnitEvent(sold, Player(PLAYER_NEUTRAL_PASSIVE), EVENT_PLAYER_UNIT_SELL, null)
    call TriggerAddAction(sold, function FP_Sold)
    call TriggerAddAction(deaths, function FP_Died)
    call TimerStart(CreateTimer(), 135.0, false, function FP_OpenTaverns)
    call TimerStart(CreateTimer(), 0.1, true, function FP_Update)
    call DisplayTimedTextToPlayer(GetLocalPlayer(), 0, 0, 20, "|cffffcc00新英雄兼容测试：|r酒馆可招募被遗忘者圣骑士。F 冲锋 / C 奉献 / E 光环 / R 大招。治疗修正为近似实现，尚待 1.24e 实测；AMAI 暂不主动招募此英雄。")
    set casts = null
    set selected = null
    set orders = null
    set sold = null
    set deaths = null
endfunction
