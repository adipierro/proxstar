/*jshint esversion: 6 */

$(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();
    initSessionTimer();
    initPendingVmRefresh();
    initVmConsole();
    initPoolSessionTimers();
    initVmListRefresh();
    initRunningVmsRefresh();
    initPageLoader();
    initVmHardware();
});

function initSessionTimer() {
    const container = $("#session-timer");
    if (!container.length) {
        return;
    }
    const forceShow = String(container.data('force-show') || '').toLowerCase() === 'true';
    const remainingEl = $("#session-timer-remaining");
    const meta = $("#session-timer-meta");
    let endTs = null;
    const tick = () => {
        if (!endTs) {
            return;
        }
        const remaining = Math.max(0, Math.floor((endTs - Date.now()) / 1000));
        const hours = Math.floor(remaining / 3600);
        const minutes = Math.floor((remaining % 3600) / 60);
        const seconds = remaining % 60;
        remainingEl.text(`${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`);
        if (remaining <= 0) {
            meta.text('(session expired)');
        }
    };
    const fetchSession = () => {
        fetch('/session', {
            credentials: 'same-origin',
        }).then((response) => {
            return response.json();
        }).then((data) => {
            if (!data.running || data.remaining_seconds === null) {
                endTs = null;
                if (!forceShow) {
                    container.hide();
                    return;
                }
                container.show();
                meta.text('(no active session)');
                remainingEl.text('--:--:--');
                return;
            }
            container.show();
            meta.text(`(running VMs: ${data.running_vms})`);
            endTs = Date.now() + (data.remaining_seconds * 1000);
            tick();
        }).catch(() => {
            if (!forceShow) {
                container.hide();
            }
        });
    };
    fetchSession();
    setInterval(tick, 1000);
    setInterval(fetchSession, 30000);
}

function initPendingVmRefresh() {
    const container = document.getElementById('vm-list');
    if (!container) {
        return;
    }
    const getPendingCards = () => document.querySelectorAll('.vm-card[data-pending="true"]');
    if (!getPendingCards().length) {
        return;
    }
    const viewUser = container.dataset.viewUser;
    const url = viewUser ? `/api/pending-vms?user=${encodeURIComponent(viewUser)}` : '/api/pending-vms';
    const pollIntervalMs = 5000;
    const poll = () => {
        fetch(url, { credentials: 'same-origin' })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('pending-vms-fetch-failed');
                }
                return response.json();
            })
            .then((data) => {
                const pending = Array.isArray(data.pending) ? data.pending : [];
                const statusMap = new Map();
                pending.forEach((entry) => {
                    if (entry && entry.name) {
                        statusMap.set(entry.name, entry.status || 'no status yet');
                    }
                });
                let shouldReload = false;
                getPendingCards().forEach((card) => {
                    const name = card.dataset.vmName;
                    if (!name) {
                        return;
                    }
                    const statusEl = card.querySelector('.vm-status-text');
                    if (statusMap.has(name)) {
                        if (statusEl) {
                            statusEl.textContent = statusMap.get(name);
                        }
                    } else {
                        shouldReload = true;
                    }
                });
                if (shouldReload || (getPendingCards().length && pending.length === 0)) {
                    window.location.reload();
                }
            })
            .catch(() => {
                // Ignore transient failures; the next poll will retry.
            });
    };
    poll();
    setInterval(poll, pollIntervalMs);
}

function initVmListRefresh() {
    const container = document.getElementById('vm-list');
    if (!container) {
        return;
    }
    const viewUser = container.dataset.viewUser;
    const url = viewUser ? `/api/vms?user=${encodeURIComponent(viewUser)}` : '/api/vms';
    const pollIntervalMs = 10000;
    const update = () => {
        fetch(url, { credentials: 'same-origin' })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('vm-list-fetch-failed');
                }
                return response.json();
            })
            .then((data) => {
                const vms = Array.isArray(data.vms) ? data.vms : [];
                const statusMap = new Map();
                vms.forEach((vm) => {
                    if (vm && vm.name) {
                        statusMap.set(vm.name, {
                            status: vm.status || 'no status yet',
                            pending: Boolean(vm.pending),
                        });
                    }
                });
                const cards = document.querySelectorAll('.vm-card');
                let shouldReload = false;
                cards.forEach((card) => {
                    const name = card.dataset.vmName;
                    if (!name) {
                        return;
                    }
                    const statusEl = card.querySelector('.vm-status-text');
                    if (!statusMap.has(name)) {
                        shouldReload = true;
                        return;
                    }
                    const data = statusMap.get(name);
                    if (statusEl) {
                        statusEl.textContent = data.status;
                    }
                    card.dataset.pending = data.pending ? 'true' : 'false';
                });
                if (shouldReload || (cards.length !== vms.length)) {
                    window.location.reload();
                }
            })
            .catch(() => {
                // Ignore transient failures; next poll will retry.
            });
    };
    update();
    setInterval(update, pollIntervalMs);
}

function initVmConsole() {
    const container = document.getElementById('vm-console');
    if (!container) {
        return;
    }
    const vmid = container.dataset.vmid;
    if (!vmid) {
        return;
    }
    const statusEl = document.getElementById('console-status');
    const frame = document.getElementById('console-frame');
    const connectConsole = () => {
        if (statusEl) {
            statusEl.textContent = 'Connecting to console...';
        }
        fetch(`/console/vm/${vmid}`, {
            credentials: 'same-origin',
            method: 'post',
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('console-fetch-failed');
                }
                return response.json();
            })
            .then((vnc_params) => {
                const src = `/static/noVNC/vnc.html?autoconnect=true&reconnect=true&reconnect_delay=2000&show_control_bar=1&showControlBar=1&resize=remote&scaling=scale&password=${encodeURIComponent(vnc_params.password)}&host=${encodeURIComponent(vnc_params.host)}&port=${encodeURIComponent(vnc_params.port)}&path=path?token=${encodeURIComponent(vnc_params.token)}`;
                if (frame) {
                    frame.src = src;
                }
                if (statusEl) {
                    statusEl.textContent = 'Connected.';
                }
            })
            .catch(() => {
                if (statusEl) {
                    statusEl.textContent = 'Unable to start console. Please try again later.';
                }
            });
    };
    connectConsole();
    const reconnect = document.getElementById('console-reconnect');
    if (reconnect) {
        reconnect.addEventListener('click', () => {
            connectConsole();
        });
    }
    const fullscreen = document.getElementById('console-fullscreen');
    if (fullscreen && frame) {
        fullscreen.addEventListener('click', () => {
            if (frame.requestFullscreen) {
                frame.requestFullscreen();
            } else if (frame.webkitRequestFullscreen) {
                frame.webkitRequestFullscreen();
            } else if (frame.mozRequestFullScreen) {
                frame.mozRequestFullScreen();
            } else if (frame.msRequestFullscreen) {
                frame.msRequestFullscreen();
            }
        });
    }
}

function initPoolSessionTimers() {
    const timers = document.querySelectorAll('.pool-session-timer');
    if (!timers.length) {
        return;
    }
    const format = (remaining) => {
        const hours = Math.floor(remaining / 3600);
        const minutes = Math.floor((remaining % 3600) / 60);
        const seconds = remaining % 60;
        return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    };
    timers.forEach((timer) => {
        const remainingEl = timer.querySelector('.pool-session-remaining');
        let remaining = parseInt(timer.dataset.sessionRemaining, 10);
        if (Number.isNaN(remaining)) {
            return;
        }
        if (remainingEl) {
            remainingEl.textContent = format(remaining);
        }
        setInterval(() => {
            remaining = Math.max(0, remaining - 1);
            if (remainingEl) {
                remainingEl.textContent = format(remaining);
            }
        }, 1000);
    });
}

function initRunningVmsRefresh() {
    const table = document.getElementById('running-vms-table');
    if (!table) {
        return;
    }
    const tbody = table.querySelector('tbody');
    const pollIntervalMs = 15000;
    const update = () => {
        fetch('/api/running-vms', { credentials: 'same-origin' })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('running-vms-fetch-failed');
                }
                return response.json();
            })
            .then((data) => {
                const vms = Array.isArray(data.vms) ? data.vms : [];
                if (!tbody) {
                    return;
                }
                if (!vms.length) {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center">No running VMs.</td></tr>';
                    return;
                }
                tbody.innerHTML = '';
                vms.forEach((vm) => {
                    const row = document.createElement('tr');
                    const vmid = (vm && vm.vmid !== undefined && vm.vmid !== null) ? vm.vmid : '';
                    const name = (vm && vm.name !== undefined && vm.name !== null) ? vm.name : '';
                    const node = (vm && vm.node !== undefined && vm.node !== null) ? vm.node : '';
                    const pool = (vm && vm.pool !== undefined && vm.pool !== null) ? vm.pool : '';
                    const status = (vm && vm.status !== undefined && vm.status !== null) ? vm.status : '';
                    row.innerHTML = `
                        <td>${vmid}</td>
                        <td>${name}</td>
                        <td>${node}</td>
                        <td>${pool}</td>
                        <td>${status}</td>
                    `;
                    tbody.appendChild(row);
                });
            })
            .catch(() => {
                // Ignore transient failures; next poll will retry.
            });
    };
    update();
    setInterval(update, pollIntervalMs);
}

function initPageLoader() {
    const loader = document.getElementById('page-loader');
    if (!loader) {
        return;
    }
    const hide = () => loader.classList.add('hidden');
    const show = () => loader.classList.remove('hidden');
    if (document.readyState === 'complete') {
        hide();
        return;
    }
    window.addEventListener('load', hide);
    document.addEventListener('click', (event) => {
        const link = event.target.closest('a');
        if (!link) {
            return;
        }
        if (link.target && link.target !== '_self') {
            return;
        }
        if (link.dataset.noLoader === 'true') {
            return;
        }
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) {
            return;
        }
        try {
            const url = new URL(href, window.location.href);
            if (url.origin !== window.location.origin) {
                return;
            }
        } catch (err) {
            return;
        }
        show();
    });
    document.addEventListener('submit', (event) => {
        if (event.defaultPrevented) {
            return;
        }
        show();
    });
}

function initVmHardware() {
    const container = document.getElementById('vm-details');
    if (!container) {
        return;
    }
    const vmid = container.dataset.vmid;
    if (!vmid) {
        return;
    }
    let usageDisk = parseInt(container.dataset.usageDisk || '0', 10);
    const limitDisk = parseInt(container.dataset.limitDisk || '0', 10);

    const nameEl = document.getElementById('vm-name');
    const nodeEl = document.getElementById('vm-node');
    const cpuEl = document.getElementById('vm-cpu');
    const memEl = document.getElementById('vm-mem');
    const statusEl = document.getElementById('vm-status');

    const startButton = document.getElementById('start-vm');
    const startMessage = document.getElementById('start-vm-message');
    const actionsLoading = document.getElementById('actions-loading');
    const deleteHint = document.getElementById('delete-vm-hint');
    const resumeButton = document.getElementById('resume-vm');
    const consoleButton = document.getElementById('console-vm');
    const suspendButton = document.getElementById('suspend-vm');
    const hibernateButton = document.getElementById('hibernate-vm');
    const shutdownButton = document.getElementById('shutdown-vm');
    const stopButton = document.getElementById('stop-vm');
    const resetButton = document.getElementById('reset-vm');
    const deleteButton = document.getElementById('delete-vm');
    const changeCoresButton = document.getElementById('change-cores');
    const changeMemButton = document.getElementById('change-mem');

    const bootText = document.getElementById('boot-order-text');
    const bootButton = document.getElementById('edit-boot-order');

    const interfacesLoading = document.getElementById('interfaces-loading');
    const interfacesEmpty = document.getElementById('interfaces-empty');
    const createNetButton = document.getElementById('create-net');

    const disksLoading = document.getElementById('disks-loading');
    const disksEmpty = document.getElementById('disks-empty');
    const createDiskButton = document.getElementById('create-disk');

    const isosLoading = document.getElementById('isos-loading');
    const isosEmpty = document.getElementById('isos-empty');
    const createIsoButton = document.getElementById('create-iso');

    const setVisible = (el, visible) => {
        if (!el) {
            return;
        }
        el.classList.toggle('d-none', !visible);
    };

    const renderItems = (items, options) => {
        const {
            loadingEl,
            emptyEl,
            createButton,
            renderItem,
        } = options;
        if (loadingEl) {
            loadingEl.remove();
        }
        if (emptyEl) {
            emptyEl.classList.add('d-none');
        }
        if (!items || !items.length) {
            if (emptyEl) {
                emptyEl.classList.remove('d-none');
            }
            return;
        }
        const anchor = createButton ? createButton.closest('li') : null;
        const parent = anchor ? anchor.parentElement : (emptyEl ? emptyEl.parentElement : null);
        if (!parent) {
            return;
        }
        items.forEach((item) => {
            const li = renderItem(item, parent);
            if (anchor) {
                parent.insertBefore(li, anchor);
            } else {
                parent.appendChild(li);
            }
        });
    };

    const updateUsageButtons = (summary) => {
        if (!summary) {
            return;
        }
        const status = summary.qmpstatus || (statusEl ? statusEl.textContent : '');
        let usageCpu = summary.usage && typeof summary.usage.cpu === 'number' ? summary.usage.cpu : 0;
        let usageMem = summary.usage && typeof summary.usage.mem === 'number' ? summary.usage.mem : 0;
        if (['running', 'paused', 'suspended'].includes(status)) {
            usageCpu = Math.max(0, usageCpu - (summary.cpu || 0));
            if (summary.mem) {
                usageMem = Math.max(0, usageMem - Math.floor(summary.mem / 1024));
            }
        }
        if (changeCoresButton) {
            changeCoresButton.dataset.usage = usageCpu;
            changeCoresButton.disabled = false;
        }
        if (changeMemButton) {
            changeMemButton.dataset.usage = usageMem;
            changeMemButton.disabled = false;
        }
        if (summary.usage && typeof summary.usage.disk === 'number') {
            usageDisk = summary.usage.disk;
            container.dataset.usageDisk = usageDisk;
            if (createDiskButton) {
                createDiskButton.dataset.usage = usageDisk;
            }
        }
    };

    const updateStartButton = (summary) => {
        if (!startButton) {
            return;
        }
        if (!summary || !summary.usage_check) {
            startButton.disabled = false;
            if (startMessage) {
                startMessage.classList.add('d-none');
                startMessage.textContent = '';
            }
            return;
        }
        startButton.disabled = true;
        const messageMap = {
            exceeds_cpu_limit: 'Insufficient CPU resources to start VM.',
            exceeds_memory_limit: 'Insufficient memory resources to start VM.',
            exceeds_disk_limit: 'Insufficient disk resources to start VM.',
        };
        if (startMessage) {
            startMessage.classList.remove('d-none');
            startMessage.textContent = messageMap[summary.usage_check] || 'Insufficient resources to start VM.';
        }
    };

    const updateActions = (summary) => {
        const status = summary ? summary.qmpstatus : null;
        if (actionsLoading) {
            actionsLoading.classList.add('d-none');
        }
        [
            startButton,
            resumeButton,
            consoleButton,
            suspendButton,
            hibernateButton,
            shutdownButton,
            stopButton,
            resetButton,
            deleteButton,
        ].forEach((el) => setVisible(el, false));
        setVisible(deleteHint, false);
        if (!status) {
            return;
        }
        if (status === 'stopped') {
            setVisible(startButton, true);
            setVisible(deleteButton, true);
        } else if (status === 'running') {
            setVisible(consoleButton, true);
            setVisible(suspendButton, true);
            setVisible(hibernateButton, true);
            setVisible(shutdownButton, true);
            setVisible(stopButton, true);
            setVisible(resetButton, true);
            setVisible(deleteHint, true);
        } else if (status === 'paused' || status === 'suspended') {
            setVisible(resumeButton, true);
            setVisible(shutdownButton, true);
            setVisible(stopButton, true);
            setVisible(resetButton, true);
            setVisible(deleteHint, true);
        }
        if (status !== 'stopped' && startMessage) {
            startMessage.classList.add('d-none');
        }
    };

    const updateSummary = (summary) => {
        if (!summary) {
            return;
        }
        if (nameEl) {
            nameEl.textContent = summary.name || `VM ${vmid}`;
        }
        if (nodeEl) {
            nodeEl.textContent = summary.node || 'Unknown';
        }
        if (cpuEl) {
            cpuEl.textContent = summary.cpu ? summary.cpu : '—';
        }
        if (memEl) {
            if (summary.mem) {
                if (summary.mem < 1024) {
                    memEl.textContent = `${summary.mem}MB`;
                } else {
                    memEl.textContent = `${Math.floor(summary.mem / 1024)}GB`;
                }
            } else {
                memEl.textContent = '—';
            }
        }
        if (summary.qmpstatus && statusEl) {
            statusEl.textContent = summary.qmpstatus;
        }
        const vmName = summary.name || vmid;
        document.querySelectorAll('[data-vmname]').forEach((el) => {
            el.dataset.vmname = vmName;
        });
        updateUsageButtons(summary);
        updateStartButton(summary);
        updateActions(summary);
    };

    const fetchHardware = () => {
        fetch(`/api/vm/${vmid}/hardware`, { credentials: 'same-origin' })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('vm-hardware-fetch-failed');
                }
                return response.json();
            })
            .then((data) => {
                const bootOrder = data.boot_order && Array.isArray(data.boot_order.order)
                    ? data.boot_order.order
                    : [];
                const enabled = bootOrder
                    .filter((entry) => entry.enabled !== false)
                    .map((entry) => entry.device)
                    .filter(Boolean);
                if (bootText) {
                    bootText.textContent = enabled.length ? enabled.join(', ') : 'None';
                }
                if (bootButton) {
                    bootButton.dataset.boot_order = data.boot_order_json || '';
                    $(bootButton).data('boot_order', data.boot_order || {});
                    bootButton.disabled = false;
                }

                renderItems(data.interfaces || [], {
                    loadingEl: interfacesLoading,
                    emptyEl: interfacesEmpty,
                    createButton: createNetButton,
                    renderItem: (iface) => {
                        const li = document.createElement('li');
                        const label = `${iface.device || ''}: ${iface.ip || 'No IP'}`;
                        li.appendChild(document.createTextNode(label + ' '));
                        const btn = document.createElement('button');
                        btn.className = 'btn btn-danger proxstar-vmbtn delete-net';
                        btn.setAttribute('data-vmid', vmid);
                        btn.setAttribute('data-interface', iface.device || '');
                        btn.innerHTML = '<i class="fas fa-trash"></i>';
                        li.appendChild(btn);
                        return li;
                    },
                });

                renderItems(data.disks || [], {
                    loadingEl: disksLoading,
                    emptyEl: disksEmpty,
                    createButton: createDiskButton,
                    renderItem: (disk) => {
                        const li = document.createElement('li');
                        const size = disk.size_gb || disk.size || '';
                        li.appendChild(
                            document.createTextNode(`${disk.device || ''}: ${size}GB `)
                        );
                        const resizeBtn = document.createElement('button');
                        resizeBtn.className = 'btn btn-default proxstar-vmbtn resize-disk';
                        resizeBtn.setAttribute('data-vmid', vmid);
                        resizeBtn.setAttribute('data-disk', disk.device || '');
                        resizeBtn.setAttribute('data-usage', usageDisk);
                        resizeBtn.setAttribute('data-limit', limitDisk);
                        resizeBtn.innerHTML = '<i class="fas fa-cog"></i>';
                        li.appendChild(resizeBtn);
                        const deleteBtn = document.createElement('button');
                        deleteBtn.className = 'btn btn-danger proxstar-vmbtn delete-disk';
                        deleteBtn.setAttribute('data-vmid', vmid);
                        deleteBtn.setAttribute('data-disk', disk.device || '');
                        deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
                        li.appendChild(deleteBtn);
                        return li;
                    },
                });

                renderItems(data.isos || [], {
                    loadingEl: isosLoading,
                    emptyEl: isosEmpty,
                    createButton: createIsoButton,
                    renderItem: (iso) => {
                        const li = document.createElement('li');
                        const label = `${iso.device || ''}: ${iso.iso || 'None'}`;
                        li.appendChild(document.createTextNode(label + ' '));
                        const changeBtn = document.createElement('button');
                        changeBtn.className = 'btn btn-default proxstar-vmbtn change-iso';
                        changeBtn.setAttribute('data-vmid', vmid);
                        changeBtn.setAttribute('data-iso', iso.device || '');
                        changeBtn.innerHTML = '<i class="fas fa-cog"></i>';
                        li.appendChild(changeBtn);
                        if (iso.iso && iso.iso !== 'None') {
                            const ejectBtn = document.createElement('button');
                            ejectBtn.className = 'btn btn-warning proxstar-vmbtn eject-iso';
                            ejectBtn.setAttribute('data-vmid', vmid);
                            ejectBtn.setAttribute('data-iso', iso.device || '');
                            ejectBtn.innerHTML = '<i class="fas fa-eject"></i>';
                            li.appendChild(ejectBtn);
                        }
                        const deleteBtn = document.createElement('button');
                        deleteBtn.className = 'btn btn-danger proxstar-vmbtn delete-iso';
                        deleteBtn.setAttribute('data-vmid', vmid);
                        deleteBtn.setAttribute('data-iso', iso.device || '');
                        deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
                        li.appendChild(deleteBtn);
                        return li;
                    },
                });
            })
            .catch(() => {
                if (bootText) {
                    bootText.textContent = 'Failed to load';
                }
                if (interfacesLoading) {
                    interfacesLoading.textContent = 'Failed to load interfaces';
                }
                if (disksLoading) {
                    disksLoading.textContent = 'Failed to load disks';
                }
                if (isosLoading) {
                    isosLoading.textContent = 'Failed to load ISOs';
                }
            });
    };

    const summaryRequest = fetch(`/api/vm/${vmid}/summary`, { credentials: 'same-origin' })
        .then((response) => {
            if (!response.ok) {
                throw new Error('vm-summary-fetch-failed');
            }
            return response.json();
        });
    const hardwareRequest = fetch(`/api/vm/${vmid}/hardware`, { credentials: 'same-origin' })
        .then((response) => {
            if (!response.ok) {
                throw new Error('vm-hardware-fetch-failed');
            }
            return response.json();
        });
    Promise.allSettled([summaryRequest, hardwareRequest]).then((results) => {
        const [summaryResult, hardwareResult] = results;
        if (summaryResult.status === 'fulfilled') {
            updateSummary(summaryResult.value);
        } else {
            if (nameEl) {
                nameEl.textContent = `VM ${vmid}`;
            }
            if (nodeEl) {
                nodeEl.textContent = 'Unknown';
            }
            if (cpuEl) {
                cpuEl.textContent = '—';
            }
            if (memEl) {
                memEl.textContent = '—';
            }
            if (statusEl) {
                statusEl.textContent = 'Unavailable';
            }
            updateStartButton({});
            updateActions({});
        }
        if (hardwareResult.status === 'fulfilled') {
            const data = hardwareResult.value;
            const bootOrder = data.boot_order && Array.isArray(data.boot_order.order)
                ? data.boot_order.order
                : [];
            const enabled = bootOrder
                .filter((entry) => entry.enabled !== false)
                .map((entry) => entry.device)
                .filter(Boolean);
            if (bootText) {
                bootText.textContent = enabled.length ? enabled.join(', ') : 'None';
            }
            if (bootButton) {
                bootButton.dataset.boot_order = data.boot_order_json || '';
                $(bootButton).data('boot_order', data.boot_order || {});
                bootButton.disabled = false;
            }

            renderItems(data.interfaces || [], {
                loadingEl: interfacesLoading,
                emptyEl: interfacesEmpty,
                createButton: createNetButton,
                renderItem: (iface) => {
                    const li = document.createElement('li');
                    const label = `${iface.device || ''}: ${iface.ip || 'No IP'}`;
                    li.appendChild(document.createTextNode(label + ' '));
                    const btn = document.createElement('button');
                    btn.className = 'btn btn-danger proxstar-vmbtn delete-net';
                    btn.setAttribute('data-vmid', vmid);
                    btn.setAttribute('data-interface', iface.device || '');
                    btn.innerHTML = '<i class="fas fa-trash"></i>';
                    li.appendChild(btn);
                    return li;
                },
            });

            renderItems(data.disks || [], {
                loadingEl: disksLoading,
                emptyEl: disksEmpty,
                createButton: createDiskButton,
                renderItem: (disk) => {
                    const li = document.createElement('li');
                    const size = disk.size_gb || disk.size || '';
                    li.appendChild(
                        document.createTextNode(`${disk.device || ''}: ${size}GB `)
                    );
                    const resizeBtn = document.createElement('button');
                    resizeBtn.className = 'btn btn-default proxstar-vmbtn resize-disk';
                    resizeBtn.setAttribute('data-vmid', vmid);
                    resizeBtn.setAttribute('data-disk', disk.device || '');
                    resizeBtn.setAttribute('data-usage', usageDisk);
                    resizeBtn.setAttribute('data-limit', limitDisk);
                    resizeBtn.innerHTML = '<i class="fas fa-cog"></i>';
                    li.appendChild(resizeBtn);
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'btn btn-danger proxstar-vmbtn delete-disk';
                    deleteBtn.setAttribute('data-vmid', vmid);
                    deleteBtn.setAttribute('data-disk', disk.device || '');
                    deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
                    li.appendChild(deleteBtn);
                    return li;
                },
            });

            renderItems(data.isos || [], {
                loadingEl: isosLoading,
                emptyEl: isosEmpty,
                createButton: createIsoButton,
                renderItem: (iso) => {
                    const li = document.createElement('li');
                    const label = `${iso.device || ''}: ${iso.iso || 'None'}`;
                    li.appendChild(document.createTextNode(label + ' '));
                    const changeBtn = document.createElement('button');
                    changeBtn.className = 'btn btn-default proxstar-vmbtn change-iso';
                    changeBtn.setAttribute('data-vmid', vmid);
                    changeBtn.setAttribute('data-iso', iso.device || '');
                    changeBtn.innerHTML = '<i class="fas fa-cog"></i>';
                    li.appendChild(changeBtn);
                    if (iso.iso && iso.iso !== 'None') {
                        const ejectBtn = document.createElement('button');
                        ejectBtn.className = 'btn btn-warning proxstar-vmbtn eject-iso';
                        ejectBtn.setAttribute('data-vmid', vmid);
                        ejectBtn.setAttribute('data-iso', iso.device || '');
                        ejectBtn.innerHTML = '<i class="fas fa-eject"></i>';
                        li.appendChild(ejectBtn);
                    }
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'btn btn-danger proxstar-vmbtn delete-iso';
                    deleteBtn.setAttribute('data-vmid', vmid);
                    deleteBtn.setAttribute('data-iso', iso.device || '');
                    deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
                    li.appendChild(deleteBtn);
                    return li;
                },
            });
        } else {
            if (bootText) {
                bootText.textContent = 'Failed to load';
            }
            if (interfacesLoading) {
                interfacesLoading.textContent = 'Failed to load interfaces';
            }
            if (disksLoading) {
                disksLoading.textContent = 'Failed to load disks';
            }
            if (isosLoading) {
                isosLoading.textContent = 'Failed to load ISOs';
            }
        }
    });
}

function confirmDialog(url, confirm, confirmButton, complete, error, location, danger) {
    swal({
        title: confirm,
        icon: "warning",
        buttons: {
            cancel: true,
            action: {
                text: confirmButton,
                closeModal: false,
                className: danger ? "swal-button--danger" : "swal-button--confirm",
            }
        },
        dangerMode: true,
    })
    .then((willComplete) => {
        if (willComplete) {
            fetch(url, {
                credentials: 'same-origin',
                method: 'post'
            }).then((response) => {
                return autoCloseAlert(complete);
            }).then(() => {
                window.location = location;
            }).catch(err => {
                if (err) {
                    swal("Uh oh...", error, "error");
                } else {
                    swal.stopLoading();
                    swal.close();
                }
            });
        }
    });
}

function autoCloseAlert(message, icon = "success") {
    return swal({
        text: message,
        icon: icon,
        buttons: false,
        timer: 2500,
    });
}

$("#delete-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/delete`, `Are you sure you want to delete ${vmname}?`, "Delete", `${vmname} is now being deleted.`, `Unable to delete ${vmname}. Please try again later.`, '/', true)
});

$("#stop-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/power/stop`, `Are you sure you want to stop ${vmname}?`, "Stop", `${vmname} is now stopping!`, `Unable to stop ${vmname}. Please try again later.`, `/vm/${vmid}`, true)
});

$("#reset-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/power/reset`, `Are you sure you want to reset ${vmname}?`, "Reset", `${vmname} is now resetting!`, `Unable to reset ${vmname}. Please try again later.`, `/vm/${vmid}`, true)
});

$("#shutdown-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/power/shutdown`, `Are you sure you want to shutdown ${vmname}?`, "Shutdown", `${vmname} is now shutting down!`, `Unable to shutdown ${vmname}. Please try again later.`, `/vm/${vmid}`, true)
});

$("#suspend-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/power/pause`, `Are you sure you want to pause ${vmname}?`, "Pause", `${vmname} is now pausing!`, `Unable to pause ${vmname}. Please try again later.`, `/vm/${vmid}`, true)
});

$("#hibernate-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/power/suspend`, `Are you sure you want to hibernate ${vmname}?`, "Hibernate", `${vmname} is now hibernating!`, `Unable to hibernate ${vmname}. Please try again later.`, `/vm/${vmid}`, true)
});

$("#start-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid');
    swal({
        title: `Starting ${vmname}...`,
        text: 'Please wait.',
        buttons: false,
        closeOnClickOutside: false,
        closeOnEsc: false,
    });
    fetch(`/vm/${vmid}/power/start`, {
        credentials: 'same-origin',
        method: 'post'
    }).then(async (response) => {
        if (!response.ok) {
            const text = await response.text();
            if (text === 'expired') {
                throw new Error('expired');
            }
            throw new Error('start_failed');
        }
        swal.close();
        return autoCloseAlert(`${vmname} starting...`);
    }).then(() => {
        window.location = `/vm/${vmid}`;
    }).catch(err => {
        if (err) {
            swal.close();
            if (err.message === 'expired') {
                swal("Expired VM", `${vmname} is expired and cannot be started.`, "error");
            } else {
                swal("Uh oh...", `Unable to start ${vmname}. Please try again later.`, "error");
            }
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$("#resume-vm").click(function(){
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid');
    swal({
        title: `Resume ${vmname}?`,
        icon: "warning",
        buttons: {
            cancel: true,
            confirm: {
                text: "Resume",
                closeModal: false,
            }
        },
    }).then((willResume) => {
        if (!willResume) {
            return null;
        }
        return fetch(`/vm/${vmid}/power/resume`, {
            credentials: 'same-origin',
            method: 'post'
        }).then(async (response) => {
            if (!response.ok) {
                const text = await response.text();
                if (text === 'expired') {
                    throw new Error('expired');
                }
                throw new Error('resume_failed');
            }
            return autoCloseAlert(`${vmname} resuming...`);
        }).then(() => {
            window.location = `/vm/${vmid}`;
        });
    }).catch(err => {
        if (err) {
            if (err.message === 'expired') {
                swal("Expired VM", `${vmname} is expired and cannot be resumed.`, "error");
            } else {
                swal("Uh oh...", `Unable to resume ${vmname}. Please try again later.`, "error");
            }
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(document).on('click', '.eject-iso', function(){
    const iso = $(this).data('iso');
    const vmid = $(this).data('vmid');
    confirmDialog(`/vm/${vmid}/iso/${iso}/eject`, `Are you sure you want to eject this ISO?`, "Eject", `Ejecting ISO!`, `Unable to eject ISO. Please try again later.`, `/vm/${vmid}`, true)
});


$(document).on('click', '.change-iso', function(){
    fetch(`/isos`, {
        credentials: 'same-origin',
    }).then((response) => {
        return response.json()
    }).then((json) => {
        var iso_list = document.createElement('select');
        for (i = 0; i < json.isos.length; i++) {
            iso_list.appendChild(new Option(json.isos[i], json.isos[i]));
        }
        swal({
            title: 'Choose an ISO to mount:',
            content: iso_list,
            buttons: {
                cancel: {
                    text: "Cancel",
                    visible: true,
                    closeModal: true,
                    className: "",
                },
                confirm: {
                    text: "Select",
                    closeModal: false,
                    className: "",
                }
            },
        })
        .then((willChange) => {
            if (willChange) {
                const vmid = $(this).data('vmid');
                const iso_drive = $(this).data('iso');
                const iso = $(iso_list).val();
                fetch(`/vm/${vmid}/iso/${iso_drive}/mount/${iso}`, {
                    credentials: 'same-origin',
                    method: 'post'
                }).then((response) => {
                    return autoCloseAlert(`${iso} mounting...`);
                }).then(() => {
                    window.location = `/vm/${vmid}`;
                }).catch(err => {
                    if (err) {
                        swal("Uh oh...", `Unable to mount ${iso}. Please try again later.`, "error");
                    } else {
                        swal.stopLoading();
                        swal.close();
                    }
                });
            }
       });
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to retrieve available ISOs. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$("#create-vm").click(function(){
    const name = document.getElementById('name').value.toLowerCase();
    const cores = document.getElementById('cores').value;
    const mem = document.getElementById('mem').value;
    const template = document.getElementById('template').value;
    const ssh_key = document.getElementById('ssh-key').value;
    const iso = document.getElementById('iso').value;
    const user = document.getElementById('user');
    const max_cpu = $(this).data('max_cpu');
    const max_mem = $(this).data('max_mem');
    const max_disk = $(this).data('max_disk');
    var ssh_regex = new RegExp("ssh-[a-z0-9]+ AAAA[0-9A-Za-z+/]+[=]{0,3}( [^@]+@[^@]+)?");
    var disk = document.getElementById('disk').value;
    fetch(`/template/${template}/disk`, {
        credentials: 'same-origin',
    }).then((response) => {
        return response.text()
    }).then((template_disk) => {
        if (template != 'none') {
            disk = template_disk
        }
        return disk
    }).then((disk) => {
        if (name && disk) {
            if (template != 'none' && ssh_key && !ssh_regex.test(ssh_key)) {
                swal("Uh oh...", "Invalid SSH key!", "error");
            } else if (disk > max_disk) {
                swal("Uh oh...", `Not enough disk resources. Please lower the VM disk size to ${max_disk}GB or lower.`, "error");
            } else if (cores > max_cpu) {
                swal("Uh oh...", `Not enough CPU resources. Lower the VM cores to ≤${max_cpu} or shut down other VMs.`, "error");
            } else if (mem/1024 > max_mem) {
                swal("Uh oh...", `Not enough memory resources. Lower the VM memory to ≤${max_mem}GB or shut down other VMs.`, "error");
            } else {
                fetch(`/hostname/${name}`, {
                    credentials: 'same-origin',
                }).then((response) => {
                    return response.text()
                }).then((text) => {
                    if (text == 'ok') {
                        var loader = document.createElement('div');
                        loader.setAttribute('class', 'loader');
                        var info = document.createElement('span');
                        if (template == 'none') {
                            info.innerHTML = `Cores: ${cores}<br>Memory: ${mem/1024}GB<br>Disk: ${disk}GB<br>ISO: ${iso}`;
                        } else {
                            const template_select = document.getElementById('template');
                            const template_name = template_select.options[template_select.selectedIndex].text;
                            info.innerHTML = `Cores: ${cores}<br>Memory: ${mem/1024}GB<br>Template: ${template_name}`;
                        }
                        swal({
                            title: `Are you sure you want to create ${name}?`,
                            content: info,
                            icon: "info",
                            buttons: {
                                cancel: true,
                                confirm: {
                                    text: "Create",
                                    closeModal: false,
                                }
                            }
                        })
                        .then((willCreate) => {
                            if (willCreate) {
                                var data  = new FormData();
                                data.append('name', name);
                                data.append('cores', cores);
                                data.append('mem', mem);
                                data.append('template', template);
                                data.append('disk', disk);
                                data.append('iso', iso);
                                data.append('ssh_key', ssh_key);
                                if (user) {
                                    data.append('user', user.value);
                                }
                                fetch('/vm/create', {
                                    credentials: 'same-origin',
                                    method: 'post',
                                    body: data
                                }).then((response) => {
                                    if (template == 'none') {
                                        var swal_text = `${name} is now being created. It should be good to go soon.`
                                    } else {
                                        var swal_text = `${name} is now being created. It will be running in a few seconds.`
                                    }
                                    return autoCloseAlert(`${swal_text}`);
                                }).then(() => {
                                    window.location = "/";
                                });
                            }
                        });
                    } else if (text == 'invalid') {
                        swal("Uh oh...", `That name is not a valid name! Please try another name.`, "error");
                    } else if (text == 'taken') {
                        swal("Uh oh...", `That name is not available! Please try another name.`, "error");
                    }
                }).catch(err => {
                    if (err) {
                        swal("Uh oh...", `Unable to verify name! Please try again later.`, "error");
                    } else {
                        swal.stopLoading();
                        swal.close();
                    }
                });
            }
        } else if (!name && !disk) {
            swal("Uh oh...", `You must enter a name and disk size for your VM!`, "error");
        } else if (!name) {
            swal("Uh oh...", `You must enter a name for your VM!`, "error");
        } else if (!disk) {
            swal("Uh oh...", `You must enter a disk size for your VM!`, "error");
        }
    });
});

$("#create-pool").click(function(){
    console.log("bingus");
    const name = document.getElementById('name').value.toLowerCase();
    const description = document.getElementById('description').value;
    const members = document.getElementById('members').value;
    var info = document.createElement('span');
    swal({
        title: `Are you sure you want to create "${name}"?`,
        content: info,
        icon: "info",
        buttons: {
            cancel: true,
            confirm: {
                text: "Create",
                closeModal: false,
            }
        }
    })
    .then((willCreate) => {
        if (willCreate) {
            var data  = new FormData();
            data.append('name', name);
            data.append('description', description);
            data.append('members', members);
            fetch('/pool/shared/create', {
                credentials: 'same-origin',
                method: 'POST',
                body: data
            }).then((response) => {
                console.log(response);
                var swal_text = `"${name}" is now being created. It should be good to go soon.`
                return autoCloseAlert(`${swal_text}`);
            }).then(() => {
                window.location = "/";
            });
        }
    });
});

$("#change-cores").click(function(){
    const vmid = $(this).data('vmid');
    const usage = $(this).data('usage');
    const limit = $(this).data('limit');
    var core_list = document.createElement('select');
    core_list.setAttribute('style', 'width: 25px');
    for (i = 1; i < limit - usage + 1; i++) {
        core_list.appendChild(new Option(i, i));
    }
    swal({
        title: 'Select how many cores you would like to allocate to this VM:',
        content: core_list,
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Select",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            const cores = $(core_list).val();
            fetch(`/vm/${vmid}/cpu/${cores}`, {
                credentials: 'same-origin',
                method: 'post'
            }).then((response) => {
                return autoCloseAlert(`Now applying the change to the number of cores!`);
            }).then(() => {
                window.location = `/vm/${vmid}`;
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the number of cores. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$("#change-mem").click(function(){
    const vmid = $(this).data('vmid');
    const usage = $(this).data('usage');
    const limit = $(this).data('limit');
    var mem_list = document.createElement('select');
    mem_list.setAttribute('style', 'width: 45px');
    for (i = 1; i < limit - usage + 1; i++) {
        mem_list.appendChild(new Option(`${i}GB`, i));
    }
    swal({
        title: 'Select how much memory you would like to allocate to this VM:',
        content: mem_list,
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Select",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            const mem = $(mem_list).val();
            fetch(`/vm/${vmid}/mem/${mem}`, {
                credentials: 'same-origin',
                method: 'post'
            }).then((response) => {
                return autoCloseAlert(`Now applying the change to the amount of memory!`);
            }).then(() => {
                window.location = `/vm/${vmid}`;
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the amount of memory. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(".edit-limit").click(function(){
    const user = $(this).data('user');
    const cur_cpu = $(this).data('cpu');
    const cur_mem = $(this).data('mem');
    const cur_disk = $(this).data('disk');
    var options = document.createElement('div');
    cpu_text = document.createElement('p');
    cpu_text.innerHTML = 'CPU';
    options.append(cpu_text);
    var cpu = document.createElement('input');
    cpu.type = 'number';
    cpu.defaultValue = cur_cpu;
    options.append(cpu);
    mem_text = document.createElement('p');
    mem_text.innerHTML = 'Memory (GB)';
    options.append(mem_text);
    var mem = document.createElement('input');
    mem.type = 'number';
    mem.defaultValue = cur_mem;
    options.append(mem)
    disk_text = document.createElement('p');
    disk_text.innerHTML = 'Disk (GB)';
    options.append(disk_text);
    var disk = document.createElement('input');
    disk.type = 'number';
    disk.defaultValue = cur_disk;
    options.append(disk)
    swal({
        title: `Enter the new usage limits for ${user}:`,
        content: options,
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Submit",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            var data  = new FormData();
            data.append('cpu', $(cpu).val());
            data.append('mem', $(mem).val());
            data.append('disk', $(disk).val());
            fetch(`/limits/${user}`, {
                credentials: 'same-origin',
                method: 'post',
                body: data
            }).then((response) => {
                return autoCloseAlert(`Now applying the new limits to ${user}!`);
            }).then(() => {
                window.location = "/";
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the limits for ${user}. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(".edit-shared-members").click(function(){
    const pool = $(this).data('pool');
    const currentMembers = $(this).data('members').slice(1,-1).split(', ');
    var currentMembersString = "";
    currentMembers.forEach(name => {
        currentMembersString += name.slice(1,-1) + ',';
    });
    var options = document.createElement('div');
    var members = document.createElement('input');
    members.type = 'text';
    members.defaultValue = currentMembersString.slice(0,-1);
    options.append(members);
    swal({
        title: `Enter the new member list for ${pool}:`,
        content: options,
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Submit",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            var data  = new FormData();
            data.append('members', $(members).val());
            fetch(`/pool/shared/${pool}/modify`, {
                credentials: 'same-origin',
                method: 'post',
                body: data
            }).then((response) => {
                return autoCloseAlert(`Now applying new member list to ${pool}!`);
            }).then(() => {
                window.location = "/";
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the members of ${pool}. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(".delete-user").click(function(){
    const user = $(this).data('user');
    swal({
        title: `Are you sure you want to delete the pool for ${user}?`,
        icon: "warning",
        buttons: {
            cancel: true,
            delete: {
                text: "delete",
                closeModal: false,
                className: "swal-button--danger",
            }
        },
        dangerMode: true,
    })
    .then((willDelete) => {
        if (willDelete) {
            fetch(`/user/${user}/delete`, {
                credentials: 'same-origin',
                method: 'post'
            }).then((response) => {
                return autoCloseAlert(`The pool for ${user} has been deleted!`);
            }).then(() => {
                window.location = "/";
            }).catch(err => {
                if (err) {
                    swal("Uh oh...", `Unable to delete the pool for ${user}. Please try again later.`, "error");
                } else {
                    swal.stopLoading();
                    swal.close();
                }
            });
        }
    });
});

$(".delete-pool").click(function(){
    const pool = $(this).data('pool');
    swal({
        title: `Are you sure you want to delete the pool ${pool}?`,
        icon: "warning",
        buttons: {
            cancel: true,
            delete: {
                text: "delete",
                closeModal: false,
                className: "swal-button--danger",
            }
        },
        dangerMode: true,
    })
    .then((willDelete) => {
        if (willDelete) {
            fetch(`/pool/shared/${ pool }/delete`, {
                credentials: 'same-origin',
                method: 'post'
            }).then((response) => {
                return autoCloseAlert(`The pool ${pool} has been deleted!`);
            }).then(() => {
                window.location = "/";
            }).catch(err => {
                if (err) {
                    swal("Uh oh...", `Unable to delete the pool ${pool}. Please try again later.`, "error");
                } else {
                    swal.stopLoading();
                    swal.close();
                }
            });
        }
    });
});

$(".delete-ignored-pool").click(function(){
    const pool = $(this).data('pool');
    fetch(`/pool/${pool}/ignore`, {
        credentials: 'same-origin',
        method: 'delete'
    }).then((response) => {
    location.reload();
    });
});

$(".add-ignored-pool").click(function(){
    const pool = document.getElementById('pool').value;
    fetch(`/pool/${pool}/ignore`, {
        credentials: 'same-origin',
        method: 'post'
    }).then((response) => {
    location.reload();
    });
});

function change_for_template(obj) {
    var template_element = obj;
    var selected = template_element.options[template_element.selectedIndex].value;
    var hide_area = document.getElementById('hide-for-template');
    var show_area = document.getElementById('show-for-template');

    if (selected === 'none') {
        hide_area.style.display = 'block';
        show_area.style.display = 'none';
    }
    else {
        hide_area.style.display = 'none';
        show_area.style.display = 'block';
    }
}

$(document).on('click', '#console-vm', function(){
    if (this.tagName && this.tagName.toLowerCase() === 'a') {
        return;
    }
    const vmname = $(this).data('vmname');
    const vmid = $(this).data('vmid');
    if (!vmid) {
        swal("Uh oh...", `Unable to start console for ${vmname}. Please try again later.`, "error");
        return;
    }
    window.open(`/console/${vmid}`, '_blank');
});

$(".delete-allowed-user").click(function(){
    const user = $(this).data('user');
    fetch(`/user/${user}/allow`, {
        credentials: 'same-origin',
        method: 'delete'
    }).then((response) => {
    location.reload();
    });
});

$(".add-allowed-user").click(function(){
    const user = document.getElementById('user').value;
    fetch(`/user/${user}/allow`, {
        credentials: 'same-origin',
        method: 'post'
    }).then((response) => {
    location.reload();
    });
});

$("#expire-all-sessions").click(function(){
    swal({
        title: "Expire all sessions?",
        text: "This will force all running sessions to expire and trigger shutdown on the next check.",
        icon: "warning",
        buttons: {
            cancel: true,
            action: {
                text: "Expire",
                closeModal: false,
                className: "swal-button--danger",
            }
        },
        dangerMode: true,
    }).then((willExpire) => {
        if (willExpire) {
            fetch('/admin/sessions/expire', {
                credentials: 'same-origin',
                method: 'post',
            }).then((response) => {
                if (!response.ok) {
                    throw new Error('expire_failed');
                }
                return response.json();
            }).then((data) => {
                const count = data && typeof data.expired === 'number' ? data.expired : 0;
                autoCloseAlert(`Expired ${count} sessions.`);
            }).catch(() => {
                swal("Uh oh...", "Unable to expire sessions. Please try again later.", "error");
            });
        }
    });
});

$(document).on('click', '.resize-disk', function(){
    const vmid = $(this).data('vmid');
    const disk = $(this).data('disk');
    const usage = $(this).data('usage');
    const limit = $(this).data('limit');
    swal({
        title: 'Expand Disk',
        text: 'Enter how many GB you would like to expand this disk by (GB)',
        content: {
            element: 'input',
            attributes: {
                type: 'number',
            },
        },
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Expand",
                closeModal: false,
            }
        },
    })
    .then((size) => {
        if (size) {
            if ((parseInt(usage) + parseInt(size)) <= parseInt(limit)) {
                fetch(`/vm/${vmid}/disk/${disk}/resize/${size}`, {
                    credentials: 'same-origin',
                    method: 'post'
                }).then((response) => {
                    return autoCloseAlert(`Disk size has been increased!`);
                }).then(() => {
                    window.location = `/vm/${vmid}`;
                });
            } else {
                swal("Uh oh...", `You don't have enough disk resources! Try again with a smaller size.`, "error");
            }
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to resize the disk. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(".edit-template").click(function(){
    const template_id = $(this).data('template_id');
    const template_name = $(this).data('template_name');
    const template_disk = $(this).data('template_disk');
    var options = document.createElement('div');
    name_text = document.createElement('p');
    name_text.innerHTML = 'Name';
    options.append(name_text);
    var name = document.createElement('input');
    name.defaultValue = template_name;
    options.append(name);
    disk_text = document.createElement('p');
    disk_text.innerHTML = 'Disk Size (GB)';
    options.append(disk_text);
    var disk = document.createElement('input');
    disk.type = 'number';
    disk.defaultValue = template_disk;
    options.append(disk);
    swal({
        title: `Template ${template_id}:`,
        content: options,
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Submit",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            var data  = new FormData();
            data.append('name', $(name).val());
            data.append('disk', $(disk).val());
            fetch(`/template/${template_id}/edit`, {
                credentials: 'same-origin',
                method: 'post',
                body: data
            }).then((response) => {
                return autoCloseAlert(`Template info changed!`);
            }).then(() => {
                location.reload();
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the template info. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$("#edit-boot-order").click(function(){
    const vmid = $(this).data('vmid');
    const vmname = $(this).data('vmname');
    const boot_order = $(this).data('boot_order');
    var options = renderBootOrder(boot_order);
    swal({
        title: `Select the new boot order for ${vmname} (full shutdown required for settings to take effect):`,
        content: renderBootOrder(boot_order),
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
            },
            confirm: {
                text: "Submit",
                closeModal: false,
            }
        },
    })
    .then((willChange) => {
        if (willChange) {
            var data  = new FormData();
            if (boot_order.legacy) {
                for (k = 0; k < boot_order.order.length; k++) {
                    e = document.getElementById(`boot-order-${k + 1}`);
                    data.append(`${k + 1}`, e.options[e.selectedIndex].value);
                }
            }
            else {
                document.getElementById('boot-order-sortable').childNodes.forEach((order, index) => {
                    if (order.children[1].firstChild.checked) {
                        data.append(`${index + 1}`, order.children[2].innerHTML);
                    }
                });
            }
            fetch(`/vm/${vmid}/boot_order`, {
                credentials: 'same-origin',
                method: 'post',
                body: data
            }).then((response) => {
                return autoCloseAlert(`Now applying the new boot order to ${vmname}!`);
            }).then(() => {
                window.location = `/vm/${vmid}`;
            });
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to change the boot order for ${vmname}. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

function renderBootOrder(boot_order) {
    let options = document.createElement('div');
    if (boot_order.legacy) {
        for (i = 0; i < boot_order.order.length; i++) {
            text = document.createElement('span');
            text.innerHTML = `${i + 1}. `;
            options.append(text);
            var entry = document.createElement('select');
            entry.setAttribute("id", `boot-order-${i + 1}`);
            for (j = 0; j < boot_order.order.length; j++) {
                entry.appendChild(new Option(boot_order.order[j].device, boot_order.order[j].device));
            }
            entry.selectedIndex = i;
            entry.setAttribute('style', 'width: 85px');
            options.append(entry);
            options.append(document.createElement('br'));
        }
    }
    else {
        let table = document.createElement('table');
        table.classList.add('table', 'table-sm', 'borderless', 'text-left');
        let thead = table.createTHead();
        thead.classList.add('font-weight-bold');
        let tbody = table.createTBody();
        tbody.classList.add('text-break', 'boot-order-sortable');
        tbody.id = 'boot-order-sortable';
        let hrow = thead.insertRow();
        hrow.insertCell().innerHTML = 'Order';
        hrow.insertCell().innerHTML = 'Enabled';
        hrow.insertCell().innerHTML = 'Device';
        hrow.insertCell().innerHTML = 'Description';
        for (i = 0; i < boot_order.order.length; i++) {
            let row = tbody.insertRow();
            row.id = `boot-order-${i + 1}`;
            $(row.insertCell()).append(
                $('<i>', {
                    class: 'fas fa-bars'
                }),
                $('<span>', {
                    class: 'boot-order-number',
                    id: `boot-order-number-${i + 1}`,
                    style: 'margin-left: .25rem',
                    text: `${i + 1}`
                })
            );
            let checkCell = $(row.insertCell()).addClass('text-center');
            $(checkCell).append(
                $('<input>', {
                    type: 'checkbox',
                    class: 'form-check-input boot-order-check',
                    checked: boot_order.order[i].enabled
                })
            );
            row.insertCell().innerHTML = boot_order.order[i].device;
            row.insertCell().innerHTML = boot_order.order[i].description;
        }
        new Sortable(tbody, {
            animation: 150,
            filter: '.boot-order-check',
            onEnd: function(event) {
                numberBootOrderTable();
            },
        });
        options.append(table);
    }
    return options;
}

function numberBootOrderTable() {
    let i = 0;
    $('[id^=boot-order-number]').each(function() {
        this.innerHTML = ++i;
    })
}

$(document).on('focus click', "[id^=boot-order-]", function() {
    previous = $(this).val();
}).on('change', "[id^=boot-order-]", function() {
    current = $(this).val();
    id = $(this).attr("id");
    $("[id^=boot-order-]").each(function() {
        if ($(this).attr("id") != id && $(this).val() == current) {
            $(this).val(previous);
        }
    });
});

$("#create-net").click(function(){
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/net/create`, `Are you sure you want to create a new interface?`, "Create", `Creating new interface!`, `Unable to create interface. Please try again later.`, `/vm/${vmid}`, false)
});

$(document).on('click', '.delete-net', function(){
    const vmid = $(this).data('vmid')
    const interface = $(this).data('interface')
    confirmDialog(`/vm/${vmid}/net/${interface}/delete`, `Are you sure you want to delete ${interface}?`, "Delete", `Deleting ${interface}!`, `Unable to delete interface. Please try again later.`, `/vm/${vmid}`, true)
});

$("#create-iso").click(function(){
    const vmid = $(this).data('vmid')
    confirmDialog(`/vm/${vmid}/iso/create`, `Are you sure you want to create a new ISO drive?`, "Create", `Creating new ISO drive!`, `Unable to create ISO drive. Please try again later.`, `/vm/${vmid}`, false)
});

$(document).on('click', '.delete-iso', function(){
    const vmid = $(this).data('vmid')
    const iso = $(this).data('iso')
    confirmDialog(`/vm/${vmid}/iso/${iso}/delete`, `Are you sure you want to delete ${iso}?`, "Delete", `Deleting ${iso}!`, `Unable to delete ISO drive. Please try again later.`, `/vm/${vmid}`, true)
});

$("#create-disk").click(function(){
    const vmid = $(this).data('vmid');
    const disk = $(this).data('disk');
    const usage = $(this).data('usage');
    const limit = $(this).data('limit');
    swal({
        title: 'Create New Disk',
        text: 'Enter new disk size (GB)',
        content: {
            element: 'input',
            attributes: {
                type: 'number',
            },
        },
        buttons: {
            cancel: {
                text: "Cancel",
                visible: true,
                closeModal: true,
                className: "",
            },
            confirm: {
                text: "Create",
                closeModal: false,
            }
        },
    })
    .then((size) => {
        if (size) {
            if ((parseInt(usage) + parseInt(size)) <= parseInt(limit)) {
                fetch(`/vm/${vmid}/disk/create/${size}`, {
                    credentials: 'same-origin',
                    method: 'post'
                }).then((response) => {
                    return autoCloseAlert(`Disk has been created!`);
                }).then(() => {
                    window.location = `/vm/${vmid}`;
                });
            } else {
                swal("Uh oh...", `You don't have enough disk resources! Try again with a smaller size.`, "error");
            }
        }
    }).catch(err => {
        if (err) {
            swal("Uh oh...", `Unable to create the disk. Please try again later.`, "error");
        } else {
            swal.stopLoading();
            swal.close();
        }
    });
});

$(document).on('click', '.delete-disk', function(){
    const vmid = $(this).data('vmid')
    const disk = $(this).data('disk')
    confirmDialog(`/vm/${vmid}/disk/${disk}/delete`, `Are you sure you want to delete ${disk}?`, "Delete", `Deleting ${disk}!`, `Unable to delete disk. Please try again later.`, `/vm/${vmid}`, true)
});
