const state = {
  householdId: localStorage.getItem("dishpute.householdId") || "",
  userId: localStorage.getItem("dishpute.userId") || "",
  members: [],
  calendarItems: [],
  workItems: [],
  weekStart: startOfWeek(new Date()),
  activeView: "calendar",
  taskFilter: "all",
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

async function api(path) {
  const response = await fetch(path, { headers: { "X-Actor-User-Id": state.userId } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Dishpute returned ${response.status}`);
  }
  return response.json();
}

async function loadAll() {
  if (!state.householdId || !state.userId) {
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
  $("#profile-name").textContent = current?.display_name || "Connected";
  $("#profile-initial").textContent = (current?.display_name || "D").charAt(0).toUpperCase();
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
  $$(".task-row").forEach((button) => button.addEventListener("click", () => openItem("work", button.dataset.id)));
  if (window.lucide) window.lucide.createIcons();
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
  $("#household-id").value = state.householdId;
  $("#user-id").value = state.userId;
  $("#connection-dialog").showModal();
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
  $("#connection-button").addEventListener("click", openConnectionDialog);
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
  $("#connection-form").addEventListener("submit", (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    state.householdId = $("#household-id").value.trim();
    state.userId = $("#user-id").value.trim();
    localStorage.setItem("dishpute.householdId", state.householdId);
    localStorage.setItem("dishpute.userId", state.userId);
    $("#connection-dialog").close();
    loadAll();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  if (window.lucide) window.lucide.createIcons();
  loadAll();
});
