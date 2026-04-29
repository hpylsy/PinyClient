(function () {
    const staleClass = "is-stale";

    function setBodyStale(isStale) {
        document.body.classList.toggle(staleClass, isStale);
    }

    function updateComponent(componentId, payload) {
        const root = document.querySelector(`[data-component-id="${componentId}"]`);
        if (!root || !payload) {
            return;
        }

        root.classList.toggle(staleClass, Boolean(payload.stale));

        const data = payload.data || {};
        root.querySelectorAll("[data-field]").forEach((node) => {
            const field = node.getAttribute("data-field");
            if (!field || !Object.prototype.hasOwnProperty.call(data, field)) {
                return;
            }
            const value = data[field];
            node.textContent = value === null || value === undefined || value === "" ? "--" : String(value);
        });
    }

    function handleMessage(event) {
        const payload = JSON.parse(event.data);
        const components = payload.components || {};
        Object.entries(components).forEach(([componentId, componentPayload]) => {
            updateComponent(componentId, componentPayload);
        });
        setBodyStale(false);
    }

    if (!window.EventSource) {
        setBodyStale(true);
        return;
    }

    const source = new EventSource("/api/components/events");
    source.onmessage = handleMessage;
    source.onerror = function () {
        setBodyStale(true);
    };
})();
