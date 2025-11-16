const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatBox = document.getElementById("chat-box");

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const userMessage = chatInput.value.trim();
  if (!userMessage) return;

  appendMessage("You", userMessage);
  chatInput.value = "";

  // Bot thinking placeholder
  const loadingId = appendMessage("Bot", "🤖 Thinking...");

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: userMessage }),
    });

    const data = await response.json();
    const botReply = data.answer || "❌ No reply.";

    // update normal bot reply
    updateMessage(loadingId, botReply);

  } catch (error) {
    updateMessage(loadingId, "❌ Error: Could not connect to server.");
  }
});

// append message
function appendMessage(sender, message) {
  const msgId = Date.now() + Math.random().toString(36).substr(2, 5);
  const div = document.createElement("div");

  div.id = msgId;
  div.className = sender === "You" ? "user-message" : "bot-message";
  div.innerHTML = `<strong>${sender}:</strong> ${message}`;

  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;

  return msgId;
}

// update message
function updateMessage(id, newText) {
  const div = document.getElementById(id);
  if (div) {
    const sender = div.className === "user-message" ? "You" : "Bot";
    div.innerHTML = `<strong>${sender}:</strong> ${newText}`;
  }
}
