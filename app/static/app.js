const servicesNode = document.querySelector("#services");
const summaryNode = document.querySelector("#summary");
const refreshButton = document.querySelector("#refresh");
const template = document.querySelector("#service-card");

function renderService(service) {
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".card");
  const status = fragment.querySelector(".status");
  const launch = fragment.querySelector(".launch");
  fragment.querySelector(".icon").textContent = service.icon;
  fragment.querySelector("h2").textContent = service.name;
  fragment.querySelector(".description").textContent = service.description;
  status.classList.toggle("online", service.running);
  status.querySelector("span").textContent = service.running ? "Запущен" : "Остановлен";
  const github = fragment.querySelector(".github");
  github.href = service.githubUrl;
  if (!service.githubUrl) github.hidden = true;
  launch.disabled = !service.launcherAvailable;
  launch.textContent = service.running ? "Перейти" : "Запустить";
  launch.addEventListener("click", async () => {
    if (service.running) {
      window.open(service.url, "_blank", "noopener");
      return;
    }
    launch.disabled = true;
    launch.textContent = "Запускаем…";
    try {
      const response = await fetch(
        "/api/services/" + encodeURIComponent(service.id) + "/launch",
        { method: "POST" },
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Не удалось запустить сервис");
      window.setTimeout(loadServices, 1800);
    } catch (error) {
      launch.disabled = false;
      launch.textContent = "Повторить";
      card.classList.add("error");
      card.title = error.message;
    }
  });
  return fragment;
}

async function loadServices() {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/api/services", { cache: "no-store" });
    if (!response.ok) throw new Error("Hub API unavailable");
    const payload = await response.json();
    servicesNode.replaceChildren(...payload.services.map(renderService));
    const running = payload.services.filter((service) => service.running).length;
    summaryNode.textContent =
      running + " из " + payload.services.length + " сервисов запущено";
  } catch {
    summaryNode.textContent = "Не удалось прочитать registry";
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", loadServices);
loadServices();
window.setInterval(loadServices, 10000);
