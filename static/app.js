const form = document.getElementById("event-form");
const sendButton = document.getElementById("send-button");
const loadButton = document.getElementById("load-button");
const statusElement = document.getElementById("status");
const list = document.getElementById("events-list");
const emptyMessage = document.getElementById("empty-message");

function setStatus(text, kind = "") {
  statusElement.textContent = text;
  statusElement.className = `status ${kind}`.trim();
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Ошибка сервера: ${response.status}`);
  }
  return data;
}

function formatTime(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ru-RU");
}

function renderEvents(events) {
  list.replaceChildren();
  const hasEvents = Array.isArray(events) && events.length > 0;
  emptyMessage.hidden = hasEvents;
  list.hidden = !hasEvents;

  for (const item of events || []) {
    const row = document.createElement("li");

    const number = document.createElement("span");
    number.className = "event-number";
    number.textContent = `Событие ${item.event}`;

    const time = document.createElement("time");
    time.className = "event-time";
    time.dateTime = item.time;
    time.textContent = formatTime(item.time);

    const id = document.createElement("span");
    id.className = "event-id";
    id.textContent = `#${item.id}`;

    row.append(number, time, id);
    list.append(row);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = form.querySelector('input[name="event"]:checked');
  if (!selected) {
    setStatus("Выберите одно из событий", "error");
    return;
  }

  sendButton.disabled = true;
  setStatus("Отправка...");
  try {
    const data = await request("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event: Number(selected.value),
        time: new Date().toISOString(),
      }),
    });
    setStatus(`Событие ${data.event.event} сохранено (${formatTime(data.event.time)})`, "ok");
  } catch (error) {
    setStatus(`Не удалось отправить: ${error.message}`, "error");
  } finally {
    sendButton.disabled = false;
  }
});

loadButton.addEventListener("click", async () => {
  loadButton.disabled = true;
  setStatus("Загрузка списка...");
  try {
    const data = await request("/api/events");
    renderEvents(data.events);
    setStatus(`Получено событий: ${data.events.length}`, "ok");
  } catch (error) {
    setStatus(`Не удалось получить список: ${error.message}`, "error");
  } finally {
    loadButton.disabled = false;
  }
});
