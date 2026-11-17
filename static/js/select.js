(function () {
  const locations = window.SCHOOL_LOCATIONS || [];
  const provinceSelect = document.getElementById("viloyat-select");
  const districtSelect = document.getElementById("tuman-select");
  const schoolSelect = document.getElementById("maktab-select");

  function setOptions(select, placeholder, items, valueFor, labelFor) {
    select.replaceChildren(new Option(placeholder, ""));
    items.forEach((item) => select.add(new Option(labelFor(item), valueFor(item))));
    select.disabled = items.length === 0;
  }

  const provinces = [...new Set(locations.map((location) => location.viloyat))];
  setOptions(
    provinceSelect,
    "Viloyatni tanlang",
    provinces,
    (value) => value,
    (value) => value
  );

  provinceSelect.addEventListener("change", () => {
    const districts = [
      ...new Set(
        locations
          .filter((item) => item.viloyat === provinceSelect.value)
          .map((item) => item.tuman)
      ),
    ];
    setOptions(
      districtSelect,
      "Tumanni tanlang",
      districts,
      (value) => value,
      (value) => value
    );
    setOptions(
      schoolSelect,
      "Avval tumanni tanlang",
      [],
      (item) => item.id,
      (item) => item.maktab
    );
  });

  districtSelect.addEventListener("change", () => {
    const schools = locations.filter(
      (item) =>
        item.viloyat === provinceSelect.value &&
        item.tuman === districtSelect.value
    );
    setOptions(
      schoolSelect,
      "Maktabni tanlang",
      schools,
      (item) => item.id,
      (item) => item.maktab
    );
  });
})();
