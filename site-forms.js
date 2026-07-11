(() => {
  const forms = document.querySelectorAll("[data-mailto-form]");
  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();

      const recipient = form.dataset.recipient || "shoreac1954@gmail.com";
      const subject = form.dataset.subject || "Shore A.C. website inquiry";
      const data = new FormData(form);
      const lines = [];

      data.forEach((value, key) => {
        const cleanValue = String(value).trim();
        if (!cleanValue) return;
        const label = key
          .replace(/[-_]/g, " ")
          .replace(/\b\w/g, (letter) => letter.toUpperCase());
        lines.push(`${label}: ${cleanValue}`);
      });

      const body = lines.join("\n");
      const status = form.querySelector(".form-status");
      if (status) status.textContent = "Opening your email app with the completed message.";
      window.location.href = `mailto:${recipient}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    });
  });
})();
