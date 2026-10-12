(() => {
    "use strict";

    const state = { data:null, date:null, history:null, expanded:new Set(), busy:new Set() };
    const timeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const today = () => new Intl.DateTimeFormat("en-CA", { timeZone:timeZone(), year:"numeric", month:"2-digit", day:"2-digit" }).format(new Date());
    state.date = today();
    const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const iconCheck = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-9"/></svg>';
    const nav = document.querySelector(".nav");
    const studioButton = [...(nav?.querySelectorAll(".nav-button") || [])].find(b => b.querySelector(".nav-label")?.textContent.trim() === "Studio");
    const button = document.createElement("button");
    button.className = "nav-button";
    button.innerHTML = '<span class="nav-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7.5h14M5 12h14M5 16.5h9"/><path d="m17 16.5 1.5 1.5 2.5-3"/></svg></span><span class="nav-label">Routines</span>';
    nav?.insertBefore(button, studioButton || null);

    const view = document.createElement("section");
    view.id = "routinesView";
    view.setAttribute("aria-label", "Routines");
    view.innerHTML = '<div class="routine-shell"><header class="routine-header"><div><div class="routine-kicker">Daily rhythm</div><h1 class="routine-title">Routines</h1><div class="routine-subtitle">Small things, consistently.</div></div><button class="routine-primary" id="routineCreate">New routine</button></header><div class="routine-toolbar"><button class="routine-chip" data-date-move="-1" aria-label="Previous day">‹</button><div class="routine-date-label" id="routineDateLabel"></div><button class="routine-chip" data-date-move="1" aria-label="Next day">›</button><button class="routine-chip" id="routineToday">Today</button></div><div class="routine-layout"><div class="routine-list" id="routineList"><div class="routine-empty">Loading routines…</div></div><aside class="routine-side"><div id="routineHydration"></div><div id="routineHistory"></div></aside></div></div>';
    document.querySelector(".main")?.appendChild(view);

    const canonicalViews = () => [document.querySelector(".home"), ...["apolloView","musicView","calendarView","tasksView","studioView","settingsView"].map(id => document.getElementById(id))].filter(Boolean);
    function hideRoutines() { view.classList.remove("active"); }
    function openRoutines(options={}) {
        canonicalViews().forEach(el => { el.classList.remove("active"); if (el.classList.contains("home")) el.classList.add("hidden"); });
        document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
        button.classList.add("active"); view.classList.add("active");
        if (options.routineId) state.expanded.add(options.routineId);
        history.replaceState(null, "", `?tab=routines${options.routineId ? `&routine=${encodeURIComponent(options.routineId)}` : ""}`);
        load();
    }
    window.openRoutines = openRoutines;
    button.addEventListener("click", () => openRoutines());
    document.addEventListener("click", event => {
        const other = event.target.closest?.(".nav-button");
        if (other && other !== button) hideRoutines();
    }, true);

    async function api(payload) {
        const response = await fetch("/api/routines/action", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...payload, timezone:timeZone()}) });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Could not save that change");
        return data;
    }
    async function load(silent=false) {
        if (!silent) document.getElementById("routineList").setAttribute("aria-busy", "true");
        try {
            const [data, historyData] = await Promise.all([
                fetch(`/api/routines?date=${state.date}&timezone=${encodeURIComponent(timeZone())}`).then(r => r.json()),
                fetch(`/api/routines/history?start=${shiftDate(state.date,-27)}&end=${state.date}&timezone=${encodeURIComponent(timeZone())}`).then(r => r.json())
            ]);
            state.data = data; state.history = historyData; render(); renderHome(data);
        } catch (error) { toast(error.message || "Routines are unavailable"); }
        finally { document.getElementById("routineList").removeAttribute("aria-busy"); }
    }
    function shiftDate(value, amount) { const d = new Date(`${value}T12:00:00`); d.setDate(d.getDate()+amount); return d.toISOString().slice(0,10); }
    function dateLabel(value) { if (value === today()) return "Today"; return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric"}); }
    function scheduleLabel(item) { const days=item.schedule_days||[]; if(days.length===7)return "Every day"; if(days.length===5&&days.every((v,i)=>v===i))return "Weekdays"; return days.map(i=>["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][i]).join(", "); }
    function render() {
        if (!state.data) return;
        document.getElementById("routineDateLabel").textContent = dateLabel(state.date);
        const list = document.getElementById("routineList");
        const routines = state.data.routines || [];
        list.innerHTML = routines.length ? routines.map(renderRoutine).join("") : '<div class="routine-empty"><strong>Build your first routine</strong>Group the things you want to do, then let Apollo remember the rest.<br><button class="routine-quiet" data-empty-create>Create a routine</button></div>';
        renderHydration(); renderHistory(); bindList();
    }
    function renderRoutine(item) {
        const expanded=state.expanded.has(item.id), done=item.status==="completed", unscheduled=item.status==="not_scheduled";
        const timing=item.window_start ? `${item.window_start}${item.window_end ? `–${item.window_end}` : ""}` : scheduleLabel(item);
        const progress=Math.round((item.progress||0)*100);
        return `<article class="routine-card ${expanded?"expanded":""} ${done?"is-complete":""} ${unscheduled?"is-unscheduled":""}" data-routine="${item.id}"><div class="routine-card-head"><button class="routine-card-toggle ${done?"done":""}" data-routine-toggle aria-label="${done?"Uncomplete":"Complete"} ${esc(item.title)}" ${unscheduled?"disabled":""}>${iconCheck}</button><div class="routine-card-main" data-expand tabindex="0"><div class="routine-card-name">${esc(item.title)}</div><div class="routine-card-meta">${unscheduled?"Not scheduled":done?"Complete":`${item.completed_steps}/${item.required_steps} · ${esc(timing)}`}</div></div><button class="routine-chevron" data-expand aria-label="${expanded?"Collapse":"Expand"}">${expanded?"⌃":"⌄"}</button></div><div class="routine-progress-track"><div class="routine-progress-fill" style="--progress:${progress}%"></div></div><div class="routine-body">${item.description?`<p class="routine-description">${esc(item.description)}</p>`:""}<div>${item.steps.length?item.steps.map(step=>renderStep(item,step,unscheduled)).join(""):'<div class="routine-description">No steps yet.</div>'}</div><div class="routine-actions"><button class="routine-quiet" data-add-step>Add step</button><button class="routine-quiet" data-edit-routine>Edit</button><button class="routine-quiet" data-duplicate>Duplicate</button><button class="routine-quiet" data-routine-move="-1">Move up</button><button class="routine-quiet" data-routine-move="1">Move down</button><button class="routine-quiet" data-archive>${item.archived?"Unarchive":"Archive"}</button><button class="routine-quiet" data-delete-routine>Delete</button></div></div></article>`;
    }
    function renderStep(routine,step,disabled) {
        const counter=step.step_type!=="checkbox" ? `<div class="routine-counter"><button data-count="-1" aria-label="Decrease">−</button><span>${number(step.value)}</span><button data-count="1" aria-label="Increase">+</button></div><span>${esc(step.unit||"")} / ${number(step.target)}</span>` : "";
        return `<div class="routine-step ${step.complete?"done":""}" data-step="${step.id}"><button class="routine-step-check ${step.complete?"done":""}" data-step-toggle ${disabled?"disabled":""} aria-label="${step.complete?"Uncheck":"Check"} ${esc(step.title)}">${iconCheck}</button><div class="routine-step-label">${esc(step.title)}</div><div class="routine-step-control">${counter}<button class="routine-icon-button" data-step-move="-1" title="Move earlier" aria-label="Move ${esc(step.title)} earlier">↑</button><button class="routine-icon-button" data-step-move="1" title="Move later" aria-label="Move ${esc(step.title)} later">↓</button><button class="routine-icon-button" data-edit-step aria-label="Edit ${esc(step.title)}">···</button></div></div>`;
    }
    function number(value) { return Number(value||0).toLocaleString(undefined,{maximumFractionDigits:1}); }
    function bindList() {
        const list=document.getElementById("routineList");
        list.onclick=async event => {
            if(event.target.closest("[data-empty-create]")){ openRoutineDialog(); return; }
            const card=event.target.closest("[data-routine]"); if(!card)return;
            const routine=state.data.routines.find(r=>r.id===card.dataset.routine); if(!routine)return;
            if(event.target.closest("[data-expand]")){ state.expanded.has(routine.id)?state.expanded.delete(routine.id):state.expanded.add(routine.id); render(); return; }
            if(event.target.closest("[data-routine-toggle]")){ await optimistic({action:"set_routine",routine_id:routine.id,completed:routine.status!=="completed",date:state.date,idempotency_key:crypto.randomUUID()}); return; }
            const stepEl=event.target.closest("[data-step]"); const step=stepEl&&routine.steps.find(s=>s.id===stepEl.dataset.step);
            if(step&&event.target.closest("[data-step-toggle]")){ await optimistic({action:"set_step",routine_id:routine.id,step_id:step.id,completed:!step.complete,date:state.date,idempotency_key:crypto.randomUUID()}); return; }
            const delta=Number(event.target.closest("[data-count]")?.dataset.count||0); if(step&&delta){ await optimistic({action:"set_step",routine_id:routine.id,step_id:step.id,value:Math.max(0,Number(step.value)+delta),date:state.date,idempotency_key:crypto.randomUUID()}); return; }
            const move=Number(event.target.closest("[data-step-move]")?.dataset.stepMove||0); if(step&&move){const index=routine.steps.indexOf(step),other=routine.steps[index+move];if(other){await api({action:"update_step",step_id:step.id,changes:{position:other.position}});await optimistic({action:"update_step",step_id:other.id,changes:{position:step.position}});}return;}
            if(step&&event.target.closest("[data-edit-step]")){openStepDialog(routine,step);return;}
            if(event.target.closest("[data-add-step]")){ openStepDialog(routine); return; }
            if(event.target.closest("[data-edit-routine]")){ openRoutineDialog(routine); return; }
            if(event.target.closest("[data-duplicate]")){ await optimistic({action:"duplicate_routine",routine_id:routine.id}); return; }
            const routineMove=Number(event.target.closest("[data-routine-move]")?.dataset.routineMove||0);if(routineMove){const index=state.data.routines.indexOf(routine),other=state.data.routines[index+routineMove];if(other){await api({action:"update_routine",routine_id:routine.id,changes:{position:other.position}});await optimistic({action:"update_routine",routine_id:other.id,changes:{position:routine.position}});}return;}
            if(event.target.closest("[data-archive]")){ if(confirm(`Archive “${routine.title}”? Its history will be kept.`)) await optimistic({action:"update_routine",routine_id:routine.id,changes:{archived:true}}); }
            if(event.target.closest("[data-delete-routine]")){if(confirm(`Permanently delete “${routine.title}” and all of its history? This cannot be undone.`)){const typed=prompt(`Type ${routine.title} to confirm`);if(typed===routine.title)await optimistic({action:"delete_routine",routine_id:routine.id,delete_history:true});else if(typed!==null)toast("Name did not match");}}
        };
        list.onkeydown=event=>{ if((event.key==="Enter"||event.key===" ")&&event.target.matches("[data-expand]")){event.preventDefault();event.target.click();} };
    }
    async function optimistic(payload) { const previous=state.data; try { await api(payload); await load(true); } catch(error) { state.data=previous; render(); toast(error.message); } }
    function renderHydration() {
        const h=state.data.hydration, progress=Math.round(Math.min(1,h.progress||0)*100);
        document.getElementById("routineHydration").innerHTML=`<section class="hydration-card"><div class="routine-panel-label">Water today</div><div class="hydration-value">${number(h.total_ml/1000)} L <span>/ ${number(h.goal_ml/1000)} L</span></div><div class="hydration-water"><div style="--progress:${progress}%"></div></div><div class="hydration-quick">${[150,250,500].map(n=>`<button data-water="${n}">+${n}</button>`).join("")}</div><div class="hydration-foot"><span><button class="routine-quiet" data-water-custom>Custom amount</button><button class="routine-quiet" data-water-goal>Goal</button></span>${h.entries.length?'<button class="routine-quiet" data-water-undo>Undo last</button>':""}</div></section>`;
        const panel=document.getElementById("routineHydration");
        panel.onclick=async event=>{ const quick=event.target.closest("[data-water]"); if(quick){await addWater(Number(quick.dataset.water));return;} if(event.target.closest("[data-water-custom]")){const amount=prompt("Amount in mL");if(amount)await addWater(Number(amount));} if(event.target.closest("[data-water-goal]")){const goal=prompt("Daily water goal in mL",h.goal_ml);if(goal)await optimistic({action:"update_hydration",goal_ml:Number(goal)});} if(event.target.closest("[data-water-undo]")){const last=h.entries[h.entries.length-1];if(last)await optimistic({action:"delete_hydration_entry",entry_id:last.id});} };
    }
    async function addWater(amount){ if(!Number.isFinite(amount)||amount<=0)return toast("Enter a valid amount"); await optimistic({action:"log_water",amount_ml:amount,idempotency_key:crypto.randomUUID()}); }
    function renderHistory(){ const days=state.history?.days||[],week=days.slice(-7),avg=week.length?week.reduce((n,d)=>n+(d.hydration?.total_ml||0),0)/week.length:0,consistency=week.length?week.reduce((n,d)=>n+(d.progress||0),0)/week.length:0; document.getElementById("routineHistory").innerHTML=`<section class="routine-history-panel"><div class="routine-panel-label">Last 4 weeks</div><div class="routine-heatmap">${days.map(day=>{const p=day.progress||0,l=p===0?0:p<.5?1:p<1?2:3;return `<div class="routine-heat" data-level="${l}" title="${day.date} · ${Math.round(p*100)}%"></div>`}).join("")}</div><div class="routine-description" style="margin-top:13px">This week · ${Math.round(consistency*100)}% routines · ${number(avg/1000)} L water average</div><div class="hydration-foot"><span class="routine-description">Consistency, not perfection.</span><button class="routine-quiet" data-export>Export</button></div></section>`; document.querySelector("[data-export]")?.addEventListener("click",()=>window.open(`/api/routines/export?timezone=${encodeURIComponent(timeZone())}`,"_blank")); }
    function dialog(content,onSubmit){ const back=document.createElement("div");back.className="routine-dialog-backdrop";back.innerHTML=`<div class="routine-dialog" role="dialog" aria-modal="true">${content}</div>`;document.body.appendChild(back);back.querySelector("[data-cancel]")?.addEventListener("click",()=>back.remove());back.addEventListener("click",e=>{if(e.target===back)back.remove();});back.querySelector("form")?.addEventListener("submit",async e=>{e.preventDefault();const save=back.querySelector("[type=submit]");save.disabled=true;try{await onSubmit(new FormData(e.target));back.remove();await load(true);}catch(error){toast(error.message);save.disabled=false;}});setTimeout(()=>back.querySelector("input")?.focus(),0); }
    function openRoutineDialog(routine=null){ const checked=i=>(routine?.schedule_days||[0,1,2,3,4,5,6]).includes(i)?"checked":"";dialog(`<form><h2>${routine?"Edit routine":"New routine"}</h2><label class="routine-field">Name<input name="title" maxlength="120" required value="${esc(routine?.title||"")}"></label><label class="routine-field">Description<textarea name="description" rows="2">${esc(routine?.description||"")}</textarea></label><div class="routine-field">Days<div class="routine-weekdays">${["M","T","W","T","F","S","S"].map((d,i)=>`<label><input type="checkbox" name="day" value="${i}" ${checked(i)}>${d}</label>`).join("")}</div></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><label class="routine-field">Starts<input type="time" name="window_start" value="${esc(routine?.window_start||"")}"></label><label class="routine-field">Ends<input type="time" name="window_end" value="${esc(routine?.window_end||"")}"></label></div><label class="routine-field"><span><input type="checkbox" name="reminder_start" ${routine?.reminder_start?"checked":""}> Remind me when the window begins</span></label><label class="routine-field"><span><input type="checkbox" name="reminder_end" ${routine?.reminder_end?"checked":""}> Remind me near the end if unfinished</span></label><div class="routine-dialog-actions"><button type="button" class="routine-dialog-cancel" data-cancel>Cancel</button><button class="routine-dialog-save" type="submit">Save</button></div></form>`,async form=>{const values={title:form.get("title"),description:form.get("description"),schedule_days:form.getAll("day").map(Number),window_start:form.get("window_start"),window_end:form.get("window_end"),reminder_start:form.get("reminder_start")==="on",reminder_end:form.get("reminder_end")==="on"};if(!values.schedule_days.length)throw new Error("Choose at least one day");await api(routine?{action:"update_routine",routine_id:routine.id,changes:values}:{action:"create_routine",...values});}); }
    function openStepDialog(routine,step=null){dialog(`<form><h2>${step?"Edit step":"Add a step"}</h2><label class="routine-field">Name<input name="title" required maxlength="160" value="${esc(step?.title||"")}"></label><label class="routine-field">Type<select name="step_type">${[["checkbox","Checkbox"],["counter","Counter"],["quantity","Measurable quantity"]].map(([v,l])=>`<option value="${v}" ${step?.step_type===v?"selected":""}>${l}</option>`).join("")}</select></label><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><label class="routine-field">Target<input name="target" type="number" min="0.01" step="0.01" value="${step?.target||1}"></label><label class="routine-field">Unit<input name="unit" placeholder="mL, minutes…" value="${esc(step?.unit||"")}"></label></div><label class="routine-field"><span><input type="checkbox" name="linked_hydration" ${step?.linked_hydration?"checked":""}> Link this target to water tracking</span></label><div class="routine-dialog-actions">${step?'<button type="button" class="routine-dialog-cancel" data-delete-step>Delete</button>':""}<button type="button" class="routine-dialog-cancel" data-cancel>Cancel</button><button class="routine-dialog-save" type="submit">${step?"Save":"Add step"}</button></div></form>`,async form=>{const values={title:form.get("title"),step_type:form.get("step_type"),target:Number(form.get("target")),unit:form.get("unit"),linked_hydration:form.get("linked_hydration")==="on"};return api(step?{action:"update_step",step_id:step.id,changes:values}:{action:"add_step",routine_id:routine.id,...values});});if(step){const back=document.querySelector(".routine-dialog-backdrop:last-of-type");back?.querySelector("[data-delete-step]")?.addEventListener("click",async()=>{if(confirm(`Delete “${step.title}”? Past records will stay intact.`)){await api({action:"delete_step",step_id:step.id});back.remove();await load(true);}});}}
    function toast(message){document.querySelector(".routine-toast")?.remove();const el=document.createElement("div");el.className="routine-toast";el.textContent=message;document.body.appendChild(el);setTimeout(()=>el.remove(),2600);}
    function renderHome(data){let section=document.getElementById("apolloHomeRoutines");if(!section){section=document.createElement("section");section.id="apolloHomeRoutines";section.className="apollo-home-routines home-section";const dashboard=document.querySelector(".home-section--dashboard");dashboard?.parentNode.insertBefore(section,dashboard);}const scheduled=(data.routines||[]).filter(r=>r.status!=="not_scheduled");section.innerHTML=`<div class="section-label home-section-title">Today’s routines</div><div class="apollo-home-routine-box"><div class="apollo-home-routine-bar"><div style="width:${Math.round((data.progress||0)*100)}%"></div></div>${scheduled.slice(0,3).map(r=>`<div class="apollo-home-routine-row" data-home-routine="${r.id}"><span>${esc(r.title)}</span><span>${r.status==="completed"?"Complete":`${r.completed_steps}/${r.required_steps}`}</span></div>`).join("")}${scheduled.length?`<div class="apollo-home-routine-row"><span>Hydration</span><span>${number(data.hydration.total_ml/1000)} / ${number(data.hydration.goal_ml/1000)} L</span></div>`:'<div class="routine-description">Nothing scheduled today.</div>'}</div>`;section.onclick=e=>{const row=e.target.closest("[data-home-routine]");openRoutines({routineId:row?.dataset.homeRoutine});};}
    document.getElementById("routineCreate").addEventListener("click",()=>openRoutineDialog());
    document.querySelectorAll("[data-date-move]").forEach(el=>el.addEventListener("click",()=>{state.date=shiftDate(state.date,Number(el.dataset.dateMove));load();}));
    document.getElementById("routineToday").addEventListener("click",()=>{state.date=today();load();});
    const params=new URLSearchParams(location.search);if(params.get("tab")==="routines"){const id=params.get("routine");if(id)state.expanded.add(id);setTimeout(()=>openRoutines({routineId:id}),0);}else{load(true);}
})();
