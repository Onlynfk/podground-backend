(function () {
  let currentTextarea = null;

  function setReactTextareaValue(textarea, value) {
    // 1️⃣ Update the actual DOM value

    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    ).set;

    nativeSetter.call(textarea, value);

    const tracker = textarea._valueTracker;
    if (tracker) {
      tracker.setValue(""); // force React diff
    }

    // 3️⃣ Dispatch a proper input event so React notices
    const event = new Event("input", { bubbles: true });
    textarea.dispatchEvent(event);
  }

  function initTinyMCE() {
    if (!window.tinymce) return;

    const textarea = document.querySelector("#description");

    if (!textarea) return;

    if (textarea === currentTextarea) {
      return;
    }

    currentTextarea = textarea;

    const existing = tinymce.get(textarea.id);

    if (existing) {
      tinymce.remove(existing);
    }

    tinymce.init({
      selector: "#description",
      menubar: false,
      height: 300,
      setup(editor) {
        editor.on("change keyup", function () {
          const textarea = editor.getElement();
          const content = editor.getContent();

          const event = new Event("input", { bubbles: true });
          textarea.dispatchEvent(event);
          setReactTextareaValue(textarea, content);
        });
      },
    });
  }

  // Initial page load
  document.addEventListener("DOMContentLoaded", initTinyMCE);

  // SPA navigation / DOM replacement
  const observer = new MutationObserver(() => initTinyMCE());

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
