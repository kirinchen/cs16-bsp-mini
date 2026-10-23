/* video_tools: toys for filming
 *   - knife dash: hold attack2 (right mouse) with the knife out to rush forward
 *   - third person: "tp" in the console or "/tp" in chat toggles an over-the-shoulder camera
 *     (cvars tp_dist 110, tp_side 24, tp_up 8)
 *   - saber: everyone's knife is drawn as a glowing beam in team colour (T red, CT blue), zaps on swing
 * cvars: dash_speed (default 750, normal run is 250), dash_trail (1 = light trail when a dash starts),
 *        saber (1 = on)
 */
#include <amxmodx>
#include <cstrike>
#include <fakemeta>
#include <engine>
#include <hamsandwich>

new g_speed, g_trail, g_trailspr, g_saber, g_beamspr;
new g_oldbuttons[33];
new const g_zap[][] = { "weapons/electro4.wav", "weapons/electro5.wav", "weapons/electro6.wav" };
new bool:g_dashing[33], bool:g_tp[33];
new g_cam[33], g_dist, g_side, g_up;

public plugin_precache()
{
	g_trailspr = precache_model("sprites/smoke.spr");
	g_beamspr = precache_model("sprites/laserbeam.spr");
	precache_model("models/rpgrocket.mdl");
	for (new i = 0; i < sizeof g_zap; i++)
		precache_sound(g_zap[i]);
}

public plugin_init()
{
	register_plugin("Video Tools", "1.0", "goldsrc-agent-kit");
	g_speed = register_cvar("dash_speed", "750");
	g_trail = register_cvar("dash_trail", "1");
	register_forward(FM_CmdStart, "fw_CmdStart");
	register_clcmd("tp", "cmd_tp");
	g_dist = register_cvar("tp_dist", "110");
	g_side = register_cvar("tp_side", "24");
	g_up = register_cvar("tp_up", "8");
	register_clcmd("say /tp", "cmd_tp");
	register_event("ResetHUD", "ev_spawn", "be");
	g_saber = register_cvar("saber", "1");
	register_forward(FM_PlayerPostThink, "fw_PlayerPostThink", 1);
	RegisterHam(Ham_Weapon_SecondaryAttack, "weapon_knife", "ham_knife_secondary");	// right mouse = dash only
}

// ---- saber: two persistent "beam" entities per player (glow + white core), moved every frame ----
// (temporary beams redrawn every 0.1 s left a trail of old blades behind a moving player)
new g_blade[33][2];

blade_points(id, Float:start[3], Float:tip[3])
{
	new Float:org[3], Float:ang[3], Float:fwd[3], Float:right[3];
	pev(id, pev_origin, org);
	pev(id, pev_v_angle, ang);
	engfunc(EngFunc_MakeVectors, ang);
	global_get(glb_v_forward, fwd);
	global_get(glb_v_right, right);
	fwd[2] = 0.0;					// held up and forward like a sword, whatever the pitch:
	for (new k = 0; k < 3; k++)			// a blade along the view line is invisible from a chase cam
	{
		start[k] = org[k] + fwd[k] * 10.0 + right[k] * 10.0;
		tip[k] = start[k] + fwd[k] * 24.0;
	}
	tip[2] += 40.0;
}

blade_create(Float:width, r, g, b, Float:bright)
{
	new ent = engfunc(EngFunc_CreateNamedEntity, engfunc(EngFunc_AllocString, "beam"));
	if (!pev_valid(ent))
		return 0;
	set_pev(ent, pev_flags, pev(ent, pev_flags) | FL_CUSTOMENTITY);
	set_pev(ent, pev_model, "sprites/laserbeam.spr");
	set_pev(ent, pev_modelindex, g_beamspr);
	set_pev(ent, pev_scale, width);			// beam width
	new Float:col[3];
	col[0] = float(r); col[1] = float(g); col[2] = float(b);
	set_pev(ent, pev_rendercolor, col);
	set_pev(ent, pev_renderamt, bright);
	set_pev(ent, pev_rendermode, 0);		// BEAM_POINTS: origin = start, angles = end
	set_pev(ent, pev_body, 0);			// noise
	set_pev(ent, pev_frame, 0.0);
	set_pev(ent, pev_animtime, 0.0);		// scroll
	set_pev(ent, pev_effects, EF_NODRAW);
	return ent;
}

blade_move(ent, const Float:start[3], const Float:tip[3])
{
	new Float:mins[3], Float:maxs[3];
	for (new k = 0; k < 3; k++)
	{
		mins[k] = floatmin(start[k], tip[k]) - start[k];
		maxs[k] = floatmax(start[k], tip[k]) - start[k];
	}
	engfunc(EngFunc_SetOrigin, ent, start);
	engfunc(EngFunc_SetSize, ent, mins, maxs);
	set_pev(ent, pev_angles, tip);
}

blade_hide(id)
{
	for (new i = 0; i < 2; i++)
		if (g_blade[id][i] && pev_valid(g_blade[id][i]))
			set_pev(g_blade[id][i], pev_effects, EF_NODRAW);
}

public fw_PlayerPostThink(id)
{
	if (g_tp[id] && g_cam[id] && pev_valid(g_cam[id]))
		cam_move(id);
	if (!get_pcvar_num(g_saber) || !is_user_alive(id) || get_user_weapon(id) != CSW_KNIFE)
	{
		blade_hide(id);
		return FMRES_IGNORED;
	}
	new r = 40, g = 120, b = 255;			// CT blue
	if (cs_get_user_team(id) == CS_TEAM_T)
	{
		r = 255; g = 40; b = 20;		// T red
	}
	if (!g_blade[id][0] || !pev_valid(g_blade[id][0]))
		g_blade[id][0] = blade_create(48.0, r, g, b, 170.0);
	if (!g_blade[id][1] || !pev_valid(g_blade[id][1]))
		g_blade[id][1] = blade_create(14.0, 255, 255, 255, 235.0);
	new Float:col[3];
	col[0] = float(r); col[1] = float(g); col[2] = float(b);
	set_pev(g_blade[id][0], pev_rendercolor, col);	// team may have changed
	new Float:start[3], Float:tip[3];
	blade_points(id, start, tip);
	for (new i = 0; i < 2; i++)
	{
		blade_move(g_blade[id][i], start, tip);
		set_pev(g_blade[id][i], pev_effects, 0);
	}
	return FMRES_IGNORED;
}

public ham_knife_secondary(knife)
{
	return HAM_SUPERCEDE;
}

public client_putinserver(id)
{
	// the client predicts its own weapon animations (cl_lw 1) and played the heavy stab on right
	// mouse before the server could refuse it; on a local listen server prediction buys nothing
	if (!is_user_bot(id))
		client_cmd(id, "cl_lw 0");
}

public client_disconnected(id)
{
	for (new i = 0; i < 2; i++)
	{
		if (g_blade[id][i] && pev_valid(g_blade[id][i]))
			engfunc(EngFunc_RemoveEntity, g_blade[id][i]);
		g_blade[id][i] = 0;
	}
	g_dashing[id] = false;
	if (g_tp[id])
		cam_off(id);
	g_tp[id] = false;
}

// ---- third person: our own camera entity, behind and over the right shoulder (GTA style) ----

cam_on(id)
{
	if (!g_cam[id] || !pev_valid(g_cam[id]))
	{
		new cam = engfunc(EngFunc_CreateNamedEntity, engfunc(EngFunc_AllocString, "info_target"));
		if (!pev_valid(cam))
			return;
		set_pev(cam, pev_classname, "vt_camera");
		engfunc(EngFunc_SetModel, cam, "models/rpgrocket.mdl");
		set_pev(cam, pev_solid, SOLID_NOT);
		set_pev(cam, pev_movetype, MOVETYPE_NOCLIP);
		set_pev(cam, pev_rendermode, kRenderTransTexture);
		set_pev(cam, pev_renderamt, 0.0);
		g_cam[id] = cam;
	}
	cam_move(id);
	engfunc(EngFunc_SetView, id, g_cam[id]);
}

cam_off(id)
{
	if (is_user_connected(id))
		engfunc(EngFunc_SetView, id, id);
	if (g_cam[id] && pev_valid(g_cam[id]))
		engfunc(EngFunc_RemoveEntity, g_cam[id]);
	g_cam[id] = 0;
}

cam_move(id)
{
	new Float:org[3], Float:ofs[3], Float:ang[3], Float:fwd[3], Float:right[3], Float:eye[3], Float:want[3], Float:hit[3];
	pev(id, pev_origin, org);
	pev(id, pev_view_ofs, ofs);
	pev(id, pev_v_angle, ang);
	engfunc(EngFunc_MakeVectors, ang);
	global_get(glb_v_forward, fwd);
	global_get(glb_v_right, right);
	new Float:dist = get_pcvar_float(g_dist), Float:side = get_pcvar_float(g_side), Float:up = get_pcvar_float(g_up);
	for (new k = 0; k < 3; k++)
	{
		eye[k] = org[k] + ofs[k];
		want[k] = eye[k] - fwd[k] * dist + right[k] * side;
	}
	want[2] += up;
	engfunc(EngFunc_TraceLine, eye, want, IGNORE_MONSTERS, id, 0);	// do not put the camera inside a wall
	new Float:frac;
	get_tr2(0, TR_flFraction, frac);
	get_tr2(0, TR_vecEndPos, hit);
	if (frac < 1.0)
		for (new k = 0; k < 3; k++)
			hit[k] += (eye[k] - hit[k]) * 0.15;
	engfunc(EngFunc_SetOrigin, g_cam[id], hit);
	set_pev(g_cam[id], pev_angles, ang);
	set_pev(g_cam[id], pev_v_angle, ang);
}

public cmd_tp(id)
{
	g_tp[id] = !g_tp[id];
	if (g_tp[id])
		cam_on(id);
	else
		cam_off(id);
	return PLUGIN_HANDLED;
}

public ev_spawn(id)
{
	if (g_tp[id])
		set_task(0.1, "reapply_view", id);
}

public reapply_view(id)
{
	if (is_user_connected(id) && g_tp[id])
		cam_on(id);
}

public fw_CmdStart(id, uc, seed)
{
	if (!is_user_alive(id))
		return FMRES_IGNORED;
	new buttons = get_uc(uc, UC_Buttons);
	if (get_user_weapon(id) == CSW_KNIFE)
	{
		// right mouse is the dash: push the knife's next secondary attack (m_flNextSecondaryAttack,
		// weapon offset 47, linux +4) ahead every command, so neither the server nor the client's
		// weapon prediction ever starts the heavy stab
		new knife = get_pdata_cbase(id, 373, 5);	// m_pActiveItem
		if (pev_valid(knife))
			set_pdata_float(knife, 47, 0.5, 4);
	}
	if (get_pcvar_num(g_saber) && get_user_weapon(id) == CSW_KNIFE && (buttons & IN_ATTACK) && !(g_oldbuttons[id] & IN_ATTACK))
		emit_sound(id, CHAN_WEAPON, g_zap[random(sizeof g_zap)], 0.7, ATTN_NORM, 0, PITCH_NORM);
	g_oldbuttons[id] = buttons;
	if (!(buttons & IN_ATTACK2) || get_user_weapon(id) != CSW_KNIFE)
	{
		g_dashing[id] = false;
		return FMRES_IGNORED;
	}
	set_uc(uc, UC_Buttons, buttons & ~IN_ATTACK2);	// no heavy stab while dashing
	if (!g_dashing[id])
	{
		set_pev(id, pev_weaponanim, 0);		// knife idle, in case a stab was already shown
		message_begin(MSG_ONE, SVC_WEAPONANIM, _, id);
		write_byte(0);
		write_byte(pev(id, pev_body));
		message_end();
	}

	new Float:angles[3], Float:fwd[3], Float:vel[3];
	pev(id, pev_v_angle, angles);
	angles[0] = 0.0;				// along the ground, wherever the player looks
	engfunc(EngFunc_MakeVectors, angles);
	global_get(glb_v_forward, fwd);
	pev(id, pev_velocity, vel);
	new Float:speed = get_pcvar_float(g_speed);
	vel[0] = fwd[0] * speed;
	vel[1] = fwd[1] * speed;
	set_pev(id, pev_velocity, vel);

	if (!g_dashing[id] && get_pcvar_num(g_trail))
		trail(id);
	g_dashing[id] = true;
	return FMRES_HANDLED;
}

trail(id)
{
	message_begin(MSG_BROADCAST, SVC_TEMPENTITY);
	write_byte(TE_BEAMFOLLOW);
	write_short(id);
	write_short(g_trailspr);
	write_byte(8);		// life, 0.1 s units
	write_byte(6);		// width
	write_byte(255);	// r
	write_byte(200);	// g
	write_byte(80);		// b
	write_byte(180);	// brightness
	message_end();
}
