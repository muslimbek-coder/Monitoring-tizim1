(function () {
  const sessionId = window.SESSION_ID;
  let data = null;
  let currentIndex = 0;
  let remaining = 0;

  const questionBox = document.getElementById("question-box");
  const navGrid = document.getElementById("nav-grid");
  const timerEl = document.getElementById("timer");
  const progressEl = document.getElementById("progress");
  const finishBtn = document.getElementById("finish-btn");

  async function loadExam() {
    const res = await fetch(`/api/exam/${sessionId}`);
    data = await res.json();
    remaining = data.remaining_seconds;
    buildNav();
    renderQuestion(0);
    tickTimer();
    setInterval(tickTimer, 1000);
  }

  function buildNav() {
    navGrid.innerHTML = "";
    data.questions.forEach((q, i) => {
      const btn = document.createElement("button");
      btn.className = "nav-item" + (q.selected_option ? " answered" : "");
      btn.textContent = i + 1;
      btn.onclick = () => renderQuestion(i);
      btn.id = `nav-${i}`;
      navGrid.appendChild(btn);
    });
  }

  function renderQuestion(i) {
    currentIndex = i;
    const q = data.questions[i];
    progressEl.textContent = `${q.subject_name} — ${q.position_in_subject}/15`;
    const options = [
      ["a", q.option_a],
      ["b", q.option_b],
      ["c", q.option_c],
      ["d", q.option_d],
    ].filter(([, text]) => text);

    questionBox.innerHTML = `
      <h3>${i + 1}-savol: ${escapeHtml(q.question_text)}</h3>
      ${options
        .map(
          ([key, text]) => `
        <label class="option-row">
          <input type="radio" name="opt" value="${key}" ${q.selected_option === key ? "checked" : ""}>
          ${escapeHtml(text)}
        </label>`
        )
        .join("")}
    `;
    questionBox.querySelectorAll('input[name="opt"]').forEach((input) => {
      input.addEventListener("change", (e) => selectOption(q, e.target.value));
    });
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.getElementById(`nav-${i}`).classList.add("active");
  }

  async function selectOption(q, value) {
    q.selected_option = value;
    document.getElementById(`nav-${currentIndex}`).classList.add("answered");
    await fetch(`/api/exam/${sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_question_id: q.sq_id, option: value }),
    });
    checkAllAnswered();
  }

  function checkAllAnswered() {
    const allAnswered = data.questions.every((q) => q.selected_option);
    finishBtn.disabled = !allAnswered;
  }

  function tickTimer() {
    if (remaining <= 0) {
      finishExam();
      return;
    }
    remaining -= 1;
    const m = Math.floor(remaining / 60)
      .toString()
      .padStart(2, "0");
    const s = (remaining % 60).toString().padStart(2, "0");
    timerEl.textContent = `${m}:${s}`;
  }

  async function finishExam() {
    const res = await fetch(`/api/exam/${sessionId}/finish`, { method: "POST" });
    const result = await res.json();
    showResult(result);
  }

  function showResult(result) {
    document.querySelector(".exam-wrap").classList.add("hidden");
    const body = document.getElementById("result-body");
    body.innerHTML = `
      <p>To'g'ri javoblar: <b>${result.total_correct}</b> / ${result.total_questions}</p>
      <p>Umumiy ball (100 ballik): <b>${result.score_100}</b></p>
      <ul>${result.per_subject
        .map((s) => `<li>${escapeHtml(s.name)}: ${s.correct}/${s.total} (${s.percent}%)</li>`)
        .join("")}</ul>
      <hr>
      <p>Natijangizni Telegram bot orqali ko'rish uchun:</p>
      <p>Login: <b>${escapeHtml(result.login)}</b></p>
      <p>Parol (sinfingiz): <b>${escapeHtml(result.password)}</b></p>
    `;
    document.getElementById("result-overlay").classList.remove("hidden");
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  finishBtn.addEventListener("click", finishExam);

  // --- Skrinshotga qarshi, FAQAT YORDAMCHI choralar (to'liq kafolat bermaydi) ---
  document.addEventListener("copy", (e) => e.preventDefault());
  document.addEventListener("keydown", (e) => {
    if (e.key === "PrintScreen" || (e.ctrlKey && e.key === "p")) {
      e.preventDefault();
      flashWarning();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flashWarning();
  });
  window.addEventListener("blur", flashWarning);

  function flashWarning() {
    const w = document.getElementById("focus-warning");
    w.classList.remove("hidden");
    setTimeout(() => w.classList.add("hidden"), 3000);
  }

  loadExam();
})();
