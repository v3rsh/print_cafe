(() => {
  const { topics } = window.THERMOQUEST;

  const screens = {
    home: document.getElementById("screen-home"),
    topics: document.getElementById("screen-topics"),
    quiz: document.getElementById("screen-quiz"),
    result: document.getElementById("screen-result"),
  };

  const els = {
    topicList: document.getElementById("topic-list"),
    hudTopic: document.getElementById("hud-topic"),
    hudProgress: document.getElementById("hud-progress"),
    hudEnergy: document.getElementById("hud-energy"),
    progressFill: document.getElementById("progress-fill"),
    qMeta: document.getElementById("q-meta"),
    qText: document.getElementById("q-text"),
    answers: document.getElementById("answers"),
    feedback: document.getElementById("feedback"),
    feedbackTitle: document.getElementById("feedback-title"),
    feedbackText: document.getElementById("feedback-text"),
    resultTitle: document.getElementById("result-title"),
    resultScore: document.getElementById("result-score"),
    resultLead: document.getElementById("result-lead"),
    resultStats: document.getElementById("result-stats"),
  };

  const state = {
    mode: "all", // all | topic
    topicId: null,
    queue: [],
    index: 0,
    energy: 0,
    correct: 0,
    streak: 0,
    bestStreak: 0,
    answered: false,
  };

  function showScreen(name) {
    Object.entries(screens).forEach(([key, node]) => {
      const active = key === name;
      node.classList.toggle("is-active", active);
      node.hidden = !active;
    });
  }

  function buildTopicList() {
    els.topicList.innerHTML = "";
    topics.forEach((topic) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "topic-btn";
      btn.innerHTML = `
        <span class="topic-btn__index">${topic.index}</span>
        <span class="topic-btn__title">${topic.title}</span>
        <span class="topic-btn__desc">${topic.description}</span>
      `;
      btn.addEventListener("click", () => startTopic(topic.id));
      els.topicList.appendChild(btn);
    });
  }

  function shuffle(list) {
    const arr = [...list];
    for (let i = arr.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function startAll() {
    state.mode = "all";
    state.topicId = null;
    state.queue = topics.flatMap((topic) =>
      topic.questions.map((q) => ({ ...q, topicTitle: topic.title, topicIndex: topic.index }))
    );
    resetRound();
    showQuestion();
  }

  function startTopic(topicId) {
    const topic = topics.find((t) => t.id === topicId);
    if (!topic) return;
    state.mode = "topic";
    state.topicId = topicId;
    state.queue = topic.questions.map((q) => ({
      ...q,
      topicTitle: topic.title,
      topicIndex: topic.index,
    }));
    resetRound();
    showQuestion();
  }

  function resetRound() {
    state.index = 0;
    state.energy = 0;
    state.correct = 0;
    state.streak = 0;
    state.bestStreak = 0;
    state.answered = false;
    state.queue = shuffle(state.queue);
  }

  function currentQuestion() {
    return state.queue[state.index];
  }

  function showQuestion() {
    const q = currentQuestion();
    if (!q) {
      showResult();
      return;
    }

    state.answered = false;
    els.feedback.hidden = true;
    els.answers.innerHTML = "";

    const total = state.queue.length;
    const n = state.index + 1;
    els.hudTopic.textContent = state.mode === "all" ? "Все темы" : q.topicIndex;
    els.hudProgress.textContent = `${n} / ${total}`;
    els.hudEnergy.textContent = `⚡ ${state.energy}`;
    els.progressFill.style.width = `${((n - 1) / total) * 100}%`;
    els.qMeta.textContent = q.topicTitle;
    els.qText.textContent = q.text;

    q.choices.forEach((choice, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "answer";
      btn.textContent = choice;
      btn.addEventListener("click", () => onAnswer(i));
      els.answers.appendChild(btn);
    });

    showScreen("quiz");
  }

  function onAnswer(choiceIndex) {
    if (state.answered) return;
    state.answered = true;

    const q = currentQuestion();
    const buttons = [...els.answers.querySelectorAll(".answer")];
    buttons.forEach((btn, i) => {
      btn.disabled = true;
      if (i === q.correct) btn.classList.add("is-correct");
      else if (i === choiceIndex) btn.classList.add("is-wrong");
      else btn.classList.add("is-dim");
    });

    const ok = choiceIndex === q.correct;
    if (ok) {
      state.correct += 1;
      state.streak += 1;
      state.bestStreak = Math.max(state.bestStreak, state.streak);
      const bonus = 10 + Math.max(0, state.streak - 1) * 2;
      state.energy += bonus;
      els.feedbackTitle.textContent = `Верно! +${bonus} энергии`;
      els.hudEnergy.classList.remove("is-bump");
      void els.hudEnergy.offsetWidth;
      els.hudEnergy.classList.add("is-bump");
    } else {
      state.streak = 0;
      els.feedbackTitle.textContent = "Неверно";
    }

    els.hudEnergy.textContent = `⚡ ${state.energy}`;
    els.feedbackText.textContent = q.explain;
    els.feedback.hidden = false;
    els.progressFill.style.width = `${((state.index + 1) / state.queue.length) * 100}%`;
  }

  function nextQuestion() {
    state.index += 1;
    if (state.index >= state.queue.length) showResult();
    else showQuestion();
  }

  function showResult() {
    const total = state.queue.length;
    const ratio = total ? state.correct / total : 0;
    let title = "Есть над чем поработать";
    let lead = "Перечитай объяснения и попробуй тему ещё раз.";
    if (ratio === 1) {
      title = "Идеальный раунд!";
      lead = "Ты уверенно держишь первые темы физики 8 класса.";
    } else if (ratio >= 0.8) {
      title = "Отличный результат";
      lead = "Почти всё верно. Ещё один заход — и будет идеально.";
    } else if (ratio >= 0.5) {
      title = "Хороший старт";
      lead = "База уже есть. Разбери ошибки и закрепи материал.";
    }

    els.resultTitle.textContent = title;
    els.resultScore.textContent = `${state.correct} из ${total}`;
    els.resultLead.textContent = lead;
    els.resultStats.innerHTML = `
      <div class="result-stat"><strong>${state.energy}</strong><span>энергия</span></div>
      <div class="result-stat"><strong>${Math.round(ratio * 100)}%</strong><span>точность</span></div>
      <div class="result-stat"><strong>${state.bestStreak}</strong><span>серия</span></div>
    `;
    showScreen("result");
  }

  function retry() {
    if (state.mode === "topic" && state.topicId) startTopic(state.topicId);
    else startAll();
  }

  function quitQuiz() {
    showScreen("topics");
  }

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.getAttribute("data-action");
    if (action === "start-all") startAll();
    if (action === "show-topics") showScreen("topics");
    if (action === "go-home") showScreen("home");
    if (action === "next-question") nextQuestion();
    if (action === "retry") retry();
    if (action === "quit-quiz") quitQuiz();
  });

  buildTopicList();
  showScreen("home");
})();
