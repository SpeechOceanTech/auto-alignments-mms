// Date picker adapted from semantic-asr, retaining local calendar dates.
const dateFromInput = document.getElementById("filter-from");
const dateToInput = document.getElementById("filter-to");
    // Use local calendar fields: UTC conversion can shift a selected day.
    function calendarDateValue(date) {
      return `${String(date.getFullYear()).padStart(4, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }

    function calendarDateFromValue(value) {
      const parts = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value);
      if (!parts) return new Date();
      const date = new Date(0);
      date.setFullYear(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
      date.setHours(12, 0, 0, 0);
      return date;
    }

    function initDatePicker() {
    const datePicker = document.getElementById("date-picker");
    const datePickerDays = document.getElementById("date-picker-days");
    const dateFromTrigger = document.getElementById("date-from-trigger");
    const dateToTrigger = document.getElementById("date-to-trigger");
    let activeDateInput = null;
    let activeDateTrigger = null;
    let calendarMonth = null;

    function updateDateTriggers() {
      [[dateFromTrigger, dateFromInput, "开始日期"], [dateToTrigger, dateToInput, "结束日期"]].forEach(([trigger, input, label]) => {
        trigger.textContent = input.value || label;
        trigger.setAttribute("aria-label", `${label}：${input.value || "未选择"}`);
      });
    }

    function renderDatePicker(preferredDate = "") {
      const year = calendarMonth.getFullYear();
      const month = calendarMonth.getMonth();
      document.getElementById("date-picker-year").value = String(year);
      document.getElementById("date-picker-month").value = String(month);
      const first = new Date(calendarMonth);
      first.setDate(1);
      const last = new Date(first);
      last.setMonth(month + 1, 0);
      const today = calendarDateValue(new Date());
      const currentPrefix = `${String(year).padStart(4, "0")}-${String(month + 1).padStart(2, "0")}-`;
      const focusDate = preferredDate || (activeDateInput.value.startsWith(currentPrefix) ? activeDateInput.value : today.startsWith(currentPrefix) ? today : `${currentPrefix}01`);
      let content = '<span aria-hidden="true"></span>'.repeat(first.getDay());
      for (let day = 1; day <= last.getDate(); day += 1) {
        const date = new Date(first);
        date.setDate(day);
        const value = calendarDateValue(date);
        const selected = value === activeDateInput.value;
        const classes = [value === today ? "today" : "", selected ? "selected" : ""].filter(Boolean).join(" ");
        content += `<button type="button" class="${classes}" data-date="${value}" aria-label="${year}年${month + 1}月${day}日" aria-pressed="${selected}" tabindex="${value === focusDate ? 0 : -1}">${day}</button>`;
      }
      datePickerDays.innerHTML = content;
      positionDatePicker();
    }

    function positionDatePicker() {
      if (datePicker.hidden || !activeDateTrigger) return;
      const anchor = activeDateTrigger.getBoundingClientRect();
      const panel = datePicker.getBoundingClientRect();
      const left = Math.max(12, Math.min(anchor.left, window.innerWidth - panel.width - 12));
      const below = anchor.bottom + 8;
      const top = below + panel.height <= window.innerHeight - 12 ? below : Math.max(12, anchor.top - panel.height - 8);
      datePicker.style.left = `${left}px`;
      datePicker.style.top = `${top}px`;
    }

    function closeDatePicker(restoreFocus = false) {
      if (datePicker.hidden) return;
      datePicker.hidden = true;
      activeDateTrigger.setAttribute("aria-expanded", "false");
      if (restoreFocus) activeDateTrigger.focus();
      activeDateInput = null;
      activeDateTrigger = null;
    }

    function openDatePicker(input, trigger) {
      if (!datePicker.hidden && activeDateTrigger === trigger) {
        closeDatePicker(true);
        return;
      }
      closeDatePicker();
      activeDateInput = input;
      activeDateTrigger = trigger;
      calendarMonth = calendarDateFromValue(input.value);
      calendarMonth.setDate(1);
      trigger.setAttribute("aria-expanded", "true");
      datePicker.setAttribute("aria-label", trigger === dateFromTrigger ? "选择开始日期" : "选择结束日期");
      renderDatePicker();
      datePicker.hidden = false;
      positionDatePicker();
      const focusDate = input.value || calendarDateValue(new Date());
      const focusDay = datePickerDays.querySelector(`[data-date="${focusDate}"]`) || datePickerDays.querySelector("button");
      if (focusDay) focusDay.focus();
    }

    function chooseCalendarDate(value) {
      const input = activeDateInput;
      if (!input) return;
      const changed = input.value !== value;
      input.value = value;
      closeDatePicker(true);
      if (changed) input.dispatchEvent(new Event("input", {bubbles: true}));
    }

    dateFromTrigger.addEventListener("click", () => openDatePicker(dateFromInput, dateFromTrigger));
    dateToTrigger.addEventListener("click", () => openDatePicker(dateToInput, dateToTrigger));
    document.getElementById("date-picker-prev").addEventListener("click", () => { calendarMonth.setMonth(calendarMonth.getMonth() - 1); renderDatePicker(); });
    document.getElementById("date-picker-next").addEventListener("click", () => { calendarMonth.setMonth(calendarMonth.getMonth() + 1); renderDatePicker(); });
    document.getElementById("date-picker-year").addEventListener("change", (event) => {
      const year = Number(event.target.value);
      if (Number.isInteger(year) && year >= 1 && year <= 9999) calendarMonth.setFullYear(year);
      renderDatePicker();
    });
    document.getElementById("date-picker-month").addEventListener("change", (event) => {
      calendarMonth.setMonth(Number(event.target.value));
      renderDatePicker();
    });
    document.getElementById("date-picker-clear").addEventListener("click", () => chooseCalendarDate(""));
    document.getElementById("date-picker-today").addEventListener("click", () => chooseCalendarDate(calendarDateValue(new Date())));
    datePickerDays.addEventListener("click", (event) => {
      const day = event.target.closest("button[data-date]");
      if (day) chooseCalendarDate(day.dataset.date);
    });
    datePickerDays.addEventListener("keydown", (event) => {
      const day = event.target.closest("button[data-date]");
      const delta = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
      if (!day || delta === undefined) return;
      event.preventDefault();
      const date = calendarDateFromValue(day.dataset.date);
      date.setDate(date.getDate() + delta);
      const value = calendarDateValue(date);
      calendarMonth = new Date(date);
      calendarMonth.setDate(1);
      renderDatePicker(value);
      const nextDay = datePickerDays.querySelector(`[data-date="${value}"]`);
      if (nextDay) nextDay.focus();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!datePicker.hidden && !event.target.closest(".bulk-date-range")) closeDatePicker();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !datePicker.hidden) { event.preventDefault(); closeDatePicker(true); }
    });
    window.addEventListener("resize", positionDatePicker);
    window.addEventListener("scroll", positionDatePicker, true);
    dateFromInput.addEventListener("input", updateDateTriggers);
    dateToInput.addEventListener("input", updateDateTriggers);
    document.getElementById("clear-filters").addEventListener("click", () => {
      closeDatePicker();
      updateDateTriggers();
    });
    updateDateTriggers();
    }


initDatePicker();
