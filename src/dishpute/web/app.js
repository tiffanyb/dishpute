const state = {
  accessToken: localStorage.getItem("dishpute.accessToken") || "",
  householdId: localStorage.getItem("dishpute.householdId") || "",
  userId: "",
  displayName: "",
  household: null,
  members: [],
  calendarItems: [],
  workItems: [],
  weekStart: startOfWeek(new Date()),
  activeView: "calendar",
  taskFilter: "all",
  selectedTaskId: null,
  theme: localStorage.getItem("dishpute.theme") || "cooperative",
};

const memberColors = ["#28644c", "#c9563f", "#426b8a", "#a77718", "#77578c"];
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function startOfWeek(value) {
  const date = new Date(value);
  const day = date.getDay();
  date.setDate(date.getDate() - ((day + 6) % 7));
  date.setHours(0, 0, 0, 0);
  return date;
}

function addDays(value, amount) {
  const date = new Date(value);
  date.setDate(date.getDate() + amount);
  return date;
}

function sameDay(first, second) {
  return first.getFullYear() === second.getFullYear()
    && first.getMonth() === second.getMonth()
    && first.getDate() === second.getDate();
}

function memberById(id) {
  return state.members.find((member) => member.user_id === id);
}

function colorForMember(id) {
  const index = Math.max(0, state.members.findIndex((member) => member.user_id === id));
  return memberColors[index % memberColors.length];
}

function participantNames(ids) {
  if (!ids?.length) return "Unplanned";
  return ids.map((id) => memberById(id)?.display_name || "Member").join(" + ");
}

function applyTheme(theme) {
  state.theme = theme === "competitive" ? "competitive" : "cooperative";
  document.body.dataset.theme = state.theme;
  localStorage.setItem("dishpute.theme", state.theme);
  $$("#theme-switch button").forEach((button) => {
    button.classList.toggle("active", button.dataset.themeChoice === state.theme);
  });
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.accessToken) headers.Authorization = `Bearer ${state.accessToken}`;
  if (options.body) headers["Content-Type"] = "application/json";
  if (options.idempotentWrite) headers["Idempotency-Key"] = crypto.randomUUID();
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatApiError(body.detail, response.status));
  }
  if (response.status === 204) return null;
  return response.json();
}

function formatApiError(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((issue) => {
      const field = Array.isArray(issue.loc) ? issue.loc.at(-1) : null;
      const label = typeof field === "string"
        ? `${field.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase())}: `
        : "";
      return `${label}${issue.msg || "Invalid value"}`;
    }).join(" ");
  }
  return `Dishpute returned ${status}`;
}

async function bootstrap() {
  if (!state.accessToken) {
    showConnectionState();
    return;
  }
  try {
    const profile = await api("/me");
    state.userId = profile.user_id;
    state.displayName = profile.display_name;
    const selected = profile.households.find((item) => item.id === state.householdId)
      || profile.households[0];
    if (!selected) {
      showConnectionState();
      $("#household-timezone").value = Intl.DateTimeFormat().resolvedOptions().timeZone;
      $("#household-dialog").showModal();
      return;
    }
    state.householdId = selected.id;
    state.household = selected;
    localStorage.setItem("dishpute.householdId", state.householdId);
    await loadAll();
  } catch (error) {
    signOut();
    showToast(error.message);
  }
}

async function loadAll() {
  if (!state.householdId || !state.accessToken) {
    showConnectionState();
    return;
  }
  setLoading(true);
  const rangeEnd = addDays(state.weekStart, 7);
  try {
    const [members, calendarItems, workItems] = await Promise.all([
      api(`/households/${state.householdId}/members`),
      api(`/households/${state.householdId}/calendar-items?range_start=${encodeURIComponent(state.weekStart.toISOString())}&range_end=${encodeURIComponent(rangeEnd.toISOString())}`),
      api(`/households/${state.householdId}/work-items`),
    ]);
    state.members = members;
    state.calendarItems = calendarItems;
    state.workItems = workItems;
    renderHeader();
    renderCalendar();
    renderTasks();
    renderHousehold();
    showAppState();
  } catch (error) {
    showToast(error.message);
    showConnectionState();
  } finally {
    setLoading(false);
  }
}

function setLoading(loading) {
  $("#refresh-button").classList.toggle("loading", loading);
  $("#refresh-button").disabled = loading;
}

function renderHeader() {
  const current = memberById(state.userId);
  $("#profile-name").textContent = current?.display_name || state.displayName;
  $("#profile-initial").textContent = (current?.display_name || state.displayName || "D").charAt(0).toUpperCase();
  $("#household-label").textContent = `${state.members.length} household member${state.members.length === 1 ? "" : "s"}`;
  $("#member-legend").innerHTML = state.members.map((member, index) => `
    <span class="member-chip" style="--member-color:${memberColors[index % memberColors.length]}">
      <span class="member-dot"></span>${escapeHtml(member.display_name)}
    </span>`).join("");
}

function renderCalendar() {
  const weekEnd = addDays(state.weekStart, 6);
  const titleFormat = { month: "short", day: "numeric" };
  $("#week-title").textContent = `${state.weekStart.toLocaleDateString(undefined, titleFormat)} – ${weekEnd.toLocaleDateString(undefined, { ...titleFormat, year: "numeric" })}`;
  const today = new Date();
  $("#calendar-grid").innerHTML = Array.from({ length: 7 }, (_, index) => {
    const day = addDays(state.weekStart, index);
    const items = state.calendarItems.filter((item) => sameDay(new Date(item.starts_at), day));
    const itemMarkup = items.length ? items.map(calendarItemMarkup).join("") : '<div class="day-empty">No household time</div>';
    return `<article class="calendar-day ${sameDay(day, today) ? "today" : ""}">
      <header class="day-header"><strong>${day.toLocaleDateString(undefined, { weekday: "short" })}</strong><span>${day.getDate()}</span></header>
      <div class="day-items">${itemMarkup}</div>
    </article>`;
  }).join("");
  $$(".calendar-item").forEach((button) => button.addEventListener("click", () => openItem("calendar", button.dataset.id)));
}

function calendarItemMarkup(item) {
  const start = new Date(item.starts_at);
  const end = new Date(item.ends_at);
  const lead = item.participant_user_ids[0];
  const time = `${start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}–${end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  return `<button class="calendar-item ${item.item_type} ${item.work_scope} ${item.status}" data-id="${item.id}" style="--member-color:${colorForMember(lead)}" type="button">
    <time>${time}</time>
    <strong>${escapeHtml(item.title || "Household time")}</strong>
    <small>${escapeHtml(participantNames(item.participant_user_ids))}</small>
  </button>`;
}

function renderTasks() {
  const visible = state.workItems.filter((item) => state.taskFilter === "all" || item.status === state.taskFilter);
  const activeCount = state.workItems.filter((item) => item.status === "active").length;
  const completedCount = state.workItems.filter((item) => item.status === "completed").length;
  $("#task-summary").innerHTML = `<span><strong class="summary-value">${activeCount}</strong> active</span><span><strong class="summary-value">${completedCount}</strong> completed</span><span><strong class="summary-value">${state.workItems.length}</strong> total</span>`;
  $("#task-list").innerHTML = visible.length ? visible.map(taskItemMarkup).join("") : '<div class="list-empty">No work matches this view.</div>';
  $$(".task-row").forEach((button) => button.addEventListener("click", () => {
    const item = state.workItems.find((entry) => entry.id === button.dataset.id);
    if (item?.item_type === "task") openTaskDetail(item.id);
    else openItem("work", button.dataset.id);
  }));
  if (window.lucide) window.lucide.createIcons();
}

function renderHousehold() {
  $("#household-name-heading").textContent = state.household?.name || "Household";
  $("#household-timezone-label").textContent = state.household?.default_timezone || "UTC";
  $("#household-member-count").textContent = String(state.members.length);
  $("#household-member-list").innerHTML = state.members.map((member, index) => `
    <div class="member-row">
      <span class="member-avatar" style="--member-color:${memberColors[index % memberColors.length]}">${escapeHtml(member.display_name.charAt(0).toUpperCase())}</span>
      <span><strong>${escapeHtml(member.display_name)}</strong><small>Household member</small></span>
      ${member.user_id === state.userId ? '<span class="current-member">You</span>' : ""}
    </div>`).join("");
}

function openTaskCreateDialog() {
  $("#task-create-form").reset();
  $("#task-create-error").classList.add("hidden");
  $("#task-participants").innerHTML = state.members.map((member) => `
    <label class="participant-option">
      <input type="checkbox" value="${member.user_id}" ${member.user_id === state.userId ? "checked" : ""} />
      ${escapeHtml(member.display_name)}
    </label>`).join("");
  $("#task-create-dialog").showModal();
}

async function createTask(event) {
  event.preventDefault();
  const button = $("#save-task-button");
  const errorElement = $("#task-create-error");
  button.disabled = true;
  errorElement.classList.add("hidden");
  try {
    await api(`/households/${state.householdId}/tasks`, {
      method: "POST",
      idempotentWrite: true,
      body: JSON.stringify({
        title: $("#task-title").value,
        description: $("#task-description").value || null,
        category: $("#task-category").value,
        work_scope: $("#task-scope").value,
        participant_user_ids: $$("#task-participants input:checked").map((input) => input.value),
      }),
    });
    $("#task-create-dialog").close();
    state.activeView = "tasks";
    await loadAll();
    showToast("Task created");
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.classList.remove("hidden");
  } finally { button.disabled = false; }
}

function taskItemMarkup(item) {
  const completed = item.status === "completed";
  const timing = item.starts_at ? new Date(item.starts_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : (item.item_type === "task" ? "Unscheduled" : "Recorded");
  return `<button class="task-row" data-id="${item.id}" type="button">
    <span class="task-status ${completed ? "completed" : ""}">${completed ? '<i data-lucide="check"></i>' : ""}</span>
    <span class="task-title"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.category)}</small></span>
    <span class="badge ${item.work_scope}">${escapeHtml(item.work_scope)}</span>
    <span class="task-meta"><i data-lucide="user-round"></i>${escapeHtml(participantNames(item.participant_user_ids))}</span>
    <span class="task-duration">${item.duration_minutes ? `${item.duration_minutes} min` : timing}</span>
    <i data-lucide="chevron-right"></i>
  </button>`;
}

function openItem(type, id) {
  const item = type === "calendar" ? state.calendarItems.find((entry) => entry.id === id) : state.workItems.find((entry) => entry.id === id);
  if (!item) return;
  $("#item-dialog-kicker").textContent = type === "calendar" ? "Calendar item" : item.item_type.replace("_", " ");
  $("#item-dialog-title").textContent = item.title || "Household time";
  const rows = [
    ["Status", item.status],
    ["Scope", item.work_scope],
    ["People", participantNames(item.participant_user_ids)],
    ["Category", item.category],
  ];
  if (item.starts_at) rows.push(["Starts", new Date(item.starts_at).toLocaleString()]);
  if (item.ends_at) rows.push(["Ends", new Date(item.ends_at).toLocaleString()]);
  if (item.duration_minutes) rows.push(["Duration", `${item.duration_minutes} minutes`]);
  if (item.counts_toward_fairness !== null && item.counts_toward_fairness !== undefined) rows.push(["Fairness", item.counts_toward_fairness ? "Included" : "Not included"]);
  $("#item-details").innerHTML = rows.map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(String(value))}</dd>`).join("");
  $("#item-dialog").showModal();
}

async function openTaskDetail(taskId) {
  try {
    const task = await api(`/households/${state.householdId}/tasks/${taskId}`);
    state.selectedTaskId = task.id;
    $("#task-detail-title").textContent = task.title;
    $("#task-detail-description").textContent = task.description || "No description";
    const creator = memberById(task.created_by_user_id)?.display_name || "Household member";
    $("#task-detail-metadata").innerHTML = [
      ["Status", task.lifecycle_status], ["Created by", creator],
      ["Planned with", participantNames(task.participant_user_ids)],
      ["Category", task.category], ["Scope", task.work_scope],
    ].map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join("");
    $("#task-detail-time-blocks").innerHTML = task.time_blocks.length
      ? task.time_blocks.map((block) => `<div class="detail-row">${new Date(block.starts_at).toLocaleString()} – ${new Date(block.ends_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>`).join("")
      : '<div class="detail-empty">No time reserved yet.</div>';
    $("#task-detail-subtasks").innerHTML = task.subtasks.length
      ? task.subtasks.map((subtask) => `<div class="detail-row">${escapeHtml(subtask.title)} · ${escapeHtml(subtask.lifecycle_status)}</div>`).join("")
      : '<div class="detail-empty">No subtasks yet.</div>';
    $("#complete-task-button").classList.toggle("hidden", task.lifecycle_status !== "active");
    $("#cancel-task-button").classList.toggle("hidden", task.lifecycle_status !== "active");
    $("#reopen-task-button").classList.toggle("hidden", task.lifecycle_status === "active");
    $("#delete-task-button").classList.toggle("hidden", task.created_by_user_id !== state.userId);
    $("#task-detail-error").classList.add("hidden");
    $("#task-detail-dialog").showModal();
  } catch (error) { showToast(error.message); }
}

async function deleteSelectedTask() {
  const errorElement = $("#task-detail-error");
  errorElement.classList.add("hidden");
  try {
    await api(`/households/${state.householdId}/tasks/${state.selectedTaskId}`, {
      method: "DELETE",
    });
    $("#task-detail-dialog").close();
    await loadAll();
    showToast("Task deleted");
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.classList.remove("hidden");
  }
}

async function updateSelectedTaskLifecycle(lifecycleStatus) {
  const errorElement = $("#task-detail-error");
  errorElement.classList.add("hidden");
  try {
    await api(`/households/${state.householdId}/tasks/${state.selectedTaskId}/lifecycle`, {
      method: "PATCH", idempotentWrite: true,
      body: JSON.stringify({ lifecycle_status: lifecycleStatus }),
    });
    $("#task-detail-dialog").close();
    await loadAll();
    showToast(`Task ${lifecycleStatus}`);
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.classList.remove("hidden");
  }
}

function openScheduleDialog() {
  const today = new Date();
  $("#schedule-form").reset();
  $("#schedule-date").value = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"), String(today.getDate()).padStart(2, "0")].join("-");
  $("#schedule-start").value = "09:00";
  $("#schedule-end").value = "10:00";
  const task = state.workItems.find((item) => item.id === state.selectedTaskId);
  $("#schedule-participants").innerHTML = state.members.map((member) => `
    <label class="participant-option"><input type="checkbox" value="${member.user_id}" ${task?.participant_user_ids.includes(member.user_id) ? "checked" : ""} />${escapeHtml(member.display_name)}</label>`).join("");
  $("#schedule-error").classList.add("hidden");
  $("#task-detail-dialog").close();
  $("#schedule-dialog").showModal();
}

async function scheduleSelectedTask(event) {
  event.preventDefault();
  const date = $("#schedule-date").value;
  const startsAt = new Date(`${date}T${$("#schedule-start").value}`);
  const endsAt = new Date(`${date}T${$("#schedule-end").value}`);
  const errorElement = $("#schedule-error");
  if (endsAt <= startsAt) {
    errorElement.textContent = "End time must be after start time.";
    errorElement.classList.remove("hidden");
    return;
  }
  const button = $("#save-schedule-button");
  button.disabled = true;
  errorElement.classList.add("hidden");
  try {
    await api(`/households/${state.householdId}/tasks/${state.selectedTaskId}/time-blocks`, {
      method: "POST", idempotentWrite: true,
      body: JSON.stringify({
        starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(),
        participant_user_ids: $$("#schedule-participants input:checked").map((input) => input.value),
      }),
    });
    $("#schedule-dialog").close();
    state.activeView = "calendar";
    state.weekStart = startOfWeek(startsAt);
    await loadAll();
    showToast("Time reserved");
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.classList.remove("hidden");
  } finally { button.disabled = false; }
}

function openCompletedWorkDialog() {
  const now = new Date();
  $("#completed-work-form").reset();
  $("#completed-work-date").value = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
  $("#completed-work-end").value = [String(now.getHours()).padStart(2, "0"), String(now.getMinutes()).padStart(2, "0")].join(":");
  $("#completed-work-range-end").value = $("#completed-work-end").value;
  setCompletedWorkTimeMode("duration");
  $("#completed-work-participants").innerHTML = state.members.map((member) => `
    <label class="participant-option"><input type="checkbox" value="${member.user_id}" ${member.user_id === state.userId ? "checked" : ""} />${escapeHtml(member.display_name)}</label>`).join("");
  const tasks = state.workItems.filter((item) => item.item_type === "task" && item.status === "active");
  $("#completed-work-task").innerHTML = '<option value="">None</option>' + tasks.map((task) => `<option value="${task.id}">${escapeHtml(task.title)}</option>`).join("");
  $("#completed-work-error").classList.add("hidden");
  $("#completed-work-dialog").showModal();
  $("#completed-work-title").focus();
}

function setCompletedWorkTimeMode(mode) {
  $$('input[name="completed-work-time-mode"]').forEach((input) => {
    input.checked = input.value === mode;
  });
  $("#completed-work-duration-fields").classList.toggle("hidden", mode !== "duration");
  $("#completed-work-range-fields").classList.toggle("hidden", mode !== "range");
}

async function createWork(event) {
  event.preventDefault();
  const date = $("#completed-work-date").value;
  const start = $("#completed-work-start").value;
  const durationEnd = $("#completed-work-end").value;
  const rangeEnd = $("#completed-work-range-end").value;
  const duration = $("#completed-work-duration").value;
  const timeMode = $('input[name="completed-work-time-mode"]:checked')?.value || "duration";
  const title = $("#completed-work-title").value.trim();
  const note = $("#completed-work-note").value.trim();
  const description = [title, note].filter(Boolean).join("\n\n") || null;
  const errorElement = $("#completed-work-error");
  if (timeMode === "duration" && !duration) {
    errorElement.textContent = "Enter duration minutes.";
    errorElement.classList.remove("hidden");
    return;
  }
  if (timeMode === "range" && (!start || !rangeEnd)) {
    errorElement.textContent = "Enter both start time and end time.";
    errorElement.classList.remove("hidden");
    return;
  }
  let startedAt = null;
  let endedAt = null;
  let durationOverride = null;
  if (timeMode === "duration") {
    const minutes = Number(duration);
    const endTime = durationEnd || [String(new Date().getHours()).padStart(2, "0"), String(new Date().getMinutes()).padStart(2, "0")].join(":");
    endedAt = new Date(`${date}T${endTime}`);
    startedAt = new Date(endedAt.getTime() - minutes * 60 * 1000);
    durationOverride = minutes;
  } else {
    startedAt = new Date(`${date}T${start}`);
    endedAt = new Date(`${date}T${rangeEnd}`);
  }
  const isScheduled = timeMode === "range" && startedAt > new Date();
  if (isScheduled && !title) {
    errorElement.textContent = "Enter a title for scheduled work.";
    errorElement.classList.remove("hidden");
    return;
  }
  const participantIds = $$("#completed-work-participants input:checked").map((input) => input.value);
  if (!participantIds.length) {
    errorElement.textContent = "Choose at least one person under Completed by.";
    errorElement.classList.remove("hidden");
    return;
  }
  const fairness = $("#completed-work-fairness").value;
  const taskId = $("#completed-work-task").value || null;
  const button = $("#save-completed-work");
  button.disabled = true;
  errorElement.classList.add("hidden");
  try {
    if (isScheduled) {
      await api(`/households/${state.householdId}/tasks`, {
        method: "POST", idempotentWrite: true,
        body: JSON.stringify({
          title,
          description: note || null,
          category: $("#completed-work-category").value,
          work_scope: $("#completed-work-scope").value,
          participant_user_ids: participantIds,
          scheduled_start: startedAt.toISOString(),
          scheduled_end: endedAt.toISOString(),
        }),
      });
    } else {
      await api(`/households/${state.householdId}/completed-work`, {
        method: "POST", idempotentWrite: true,
        body: JSON.stringify({
          description,
          category: $("#completed-work-category").value,
          work_scope: $("#completed-work-scope").value,
          counts_toward_fairness: fairness === "auto" ? null : fairness === "include",
          participant_user_ids: participantIds,
          started_at: startedAt.toISOString(),
          ended_at: endedAt.toISOString(),
          duration_override_minutes: durationOverride,
          task_id: taskId,
          complete_task: Boolean(taskId && $("#completed-work-complete-task").checked),
        }),
      });
    }
    $("#completed-work-dialog").close();
    state.weekStart = startOfWeek(new Date(`${date}T12:00`));
    await loadAll();
    showToast(isScheduled ? "Task scheduled" : "Work recorded");
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.classList.remove("hidden");
  } finally { button.disabled = false; }
}

function showConnectionState() {
  $$(".view, .view-tabs").forEach((element) => element.classList.add("hidden"));
  $("#connection-empty-state").classList.remove("hidden");
}

function showAppState() {
  $(".view-tabs").classList.remove("hidden");
  $("#connection-empty-state").classList.add("hidden");
  switchView(state.activeView);
}

function switchView(view) {
  state.activeView = view;
  $$(".view-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  $$(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `${view}-view`);
    section.classList.remove("hidden");
  });
}

function openConnectionDialog() {
  $("#connection-dialog").showModal();
}

function signOut() {
  state.accessToken = "";
  state.householdId = "";
  state.userId = "";
  localStorage.removeItem("dishpute.accessToken");
  localStorage.removeItem("dishpute.householdId");
  $("#account-dialog").close();
  showConnectionState();
}

function setAuthMode(mode) {
  const signup = mode === "signup";
  $$("#auth-mode button").forEach((button) => button.classList.toggle("active", button.dataset.authMode === mode));
  $$(".signup-field").forEach((field) => field.classList.toggle("hidden", !signup));
  $("#display-name").required = signup;
  $("#password").minLength = signup ? 10 : 1;
  $("#password").autocomplete = signup ? "new-password" : "current-password";
  $("#auth-title").textContent = signup ? "Create your account" : "Sign in to Dishpute";
  $("#save-connection").textContent = signup ? "Create account" : "Sign in";
  $("#connection-form").dataset.mode = mode;
  $("#auth-error").classList.add("hidden");
}

function showAuthError(message) {
  const error = $("#auth-error");
  error.textContent = message;
  error.classList.remove("hidden");
}

async function createHousehold() {
  const form = $("#create-household-form");
  if (!form.reportValidity()) return;
  const button = $("#create-household-button");
  button.disabled = true;
  button.textContent = "Creating...";
  try {
    const household = await api("/households", { method: "POST", body: JSON.stringify({ name: $("#household-name").value, default_timezone: $("#household-timezone").value }) });
    state.householdId = household.id;
    localStorage.setItem("dishpute.householdId", household.id);
    $("#household-dialog").close();
    await bootstrap();
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Could not create the household");
  } finally {
    button.disabled = false;
    button.textContent = "Create household";
  }
}

async function joinHousehold() {
  const form = $("#join-household-form");
  if (!form.reportValidity()) return;
  try {
    const household = await api("/households/join", { method: "POST", body: JSON.stringify({ invite_code: $("#invite-code").value }) });
    state.householdId = household.id;
    localStorage.setItem("dishpute.householdId", household.id);
    $("#household-dialog").close();
    await bootstrap();
  } catch (error) { showToast(error.message); }
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 4000);
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function bindEvents() {
  $$(".view-tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
  $("#connection-button").addEventListener("click", () => {
    if (!state.accessToken) return openConnectionDialog();
    $("#account-name").textContent = state.displayName;
    $("#invite-result").classList.add("hidden");
    $("#account-dialog").showModal();
  });
  $("#empty-connect-button").addEventListener("click", openConnectionDialog);
  $("#refresh-button").addEventListener("click", loadAll);
  $("#today-button").addEventListener("click", () => { state.weekStart = startOfWeek(new Date()); loadAll(); });
  $("#previous-week").addEventListener("click", () => { state.weekStart = addDays(state.weekStart, -7); loadAll(); });
  $("#next-week").addEventListener("click", () => { state.weekStart = addDays(state.weekStart, 7); loadAll(); });
  $("#close-item-dialog").addEventListener("click", () => $("#item-dialog").close());
  $$("#task-filters button").forEach((button) => button.addEventListener("click", () => {
    state.taskFilter = button.dataset.filter;
    $$("#task-filters button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    renderTasks();
  }));
  $("#close-auth-dialog").addEventListener("click", () => $("#connection-dialog").close());
  $("#close-account-dialog").addEventListener("click", () => $("#account-dialog").close());
  $("#sign-out-button").addEventListener("click", signOut);
  $$("#auth-mode button").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.authMode)));
  $("#connection-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const signup = event.currentTarget.dataset.mode === "signup";
    const body = { email: $("#email").value, password: $("#password").value };
    if (signup) body.display_name = $("#display-name").value;
    $("#auth-error").classList.add("hidden");
    $("#save-connection").disabled = true;
    try {
      const result = await api(signup ? "/auth/signup" : "/auth/login", { method: "POST", body: JSON.stringify(body) });
      state.accessToken = result.access_token;
      localStorage.setItem("dishpute.accessToken", state.accessToken);
      $("#connection-dialog").close();
      await bootstrap();
    } catch (error) {
      showAuthError(
        !signup && error.message === "Invalid email or password"
          ? "That email and password do not match a Dishpute account. Try again or choose Create account."
          : error.message,
      );
    } finally {
      $("#save-connection").disabled = false;
    }
  });
  $("#create-household-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await createHousehold();
  });
  $("#join-household-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await joinHousehold();
  });
  $("#create-invite-button").addEventListener("click", async () => {
    try {
      const result = await api(`/households/${state.householdId}/invites`, { method: "POST" });
      $("#generated-invite").textContent = result.invite_code;
      $("#invite-result").classList.remove("hidden");
    } catch (error) { showToast(error.message); }
  });
  $("#household-invite-button").addEventListener("click", async () => {
    const button = $("#household-invite-button");
    button.disabled = true;
    try {
      const result = await api(`/households/${state.householdId}/invites`, { method: "POST" });
      $("#household-invite-code").textContent = result.invite_code;
      $("#household-invite-panel").classList.remove("hidden");
    } catch (error) { showToast(error.message); }
    finally { button.disabled = false; }
  });
  $("#copy-invite-button").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("#household-invite-code").textContent);
    showToast("Invitation code copied");
  });
  $$("#theme-switch button").forEach((button) => {
    button.addEventListener("click", () => applyTheme(button.dataset.themeChoice));
  });
  $("#new-task-button").addEventListener("click", openTaskCreateDialog);
  $("#close-task-create").addEventListener("click", () => $("#task-create-dialog").close());
  $("#cancel-task-create").addEventListener("click", () => $("#task-create-dialog").close());
  $("#task-create-form").addEventListener("submit", createTask);
  $("#close-task-detail").addEventListener("click", () => $("#task-detail-dialog").close());
  $("#complete-task-button").addEventListener("click", () => updateSelectedTaskLifecycle("completed"));
  $("#reopen-task-button").addEventListener("click", () => updateSelectedTaskLifecycle("active"));
  $("#cancel-task-button").addEventListener("click", () => {
    if (window.confirm("Cancel this Task? Its history will be preserved.")) updateSelectedTaskLifecycle("cancelled");
  });
  $("#delete-task-button").addEventListener("click", () => {
    if (window.confirm("Permanently delete this Task? Completed-work history will be preserved.")) {
      deleteSelectedTask();
    }
  });
  $("#reserve-time-button").addEventListener("click", openScheduleDialog);
  $("#close-schedule").addEventListener("click", () => $("#schedule-dialog").close());
  $("#cancel-schedule").addEventListener("click", () => $("#schedule-dialog").close());
  $("#schedule-form").addEventListener("submit", scheduleSelectedTask);
  $("#record-work-button").addEventListener("click", openCompletedWorkDialog);
  $("#close-completed-work").addEventListener("click", () => $("#completed-work-dialog").close());
  $("#cancel-completed-work").addEventListener("click", () => $("#completed-work-dialog").close());
  $("#completed-work-form").addEventListener("submit", createWork);
  $$('input[name="completed-work-time-mode"]').forEach((input) => {
    input.addEventListener("change", () => setCompletedWorkTimeMode(input.value));
  });
  document.addEventListener("keydown", (event) => {
    if (event.shiftKey && event.key.toLowerCase() === "c" && !event.metaKey && !event.ctrlKey && !event.altKey) {
      const target = event.target;
      const isTyping = target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (!isTyping && !$("#completed-work-dialog").open) {
        event.preventDefault();
        openCompletedWorkDialog();
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  applyTheme(state.theme);
  setAuthMode("login");
  if (window.lucide) window.lucide.createIcons();
  bootstrap();
});
