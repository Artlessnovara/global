let localStream;
const peerConnections = new Map();
let socket;
let conversationId;

const servers = {
    iceServers: [
        {
            urls: ['stun:stun1.l.google.com:19302', 'stun:stun2.l.google.com:19302'],
        },
    ],
};

async function init(convoId) {
    conversationId = convoId;
    socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);

    try {
        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        document.getElementById('local-video').srcObject = localStream;
    } catch (error) {
        console.error("Error accessing media devices.", error);
        alert("Could not access camera/microphone.");
        return;
    }

    setupSocketListeners();
    addControlListeners();

    socket.emit('join-call-room', { room: conversationId });
}

function setupSocketListeners() {
    socket.on('existing-peers', (sids) => {
        console.log('Existing peers:', sids);
        sids.forEach(sid => {
            createPeerConnection(sid, true);
        });
    });

    socket.on('new-peer', (data) => {
        console.log('New peer joined:', data.sid);
        createPeerConnection(data.sid, false);
    });

    socket.on('offer', async (data) => {
        console.log('Offer received from:', data.from_sid);
        const pc = getPeerConnection(data.from_sid, false); // Important: initiator is false here
        await pc.setRemoteDescription(new RTCSessionDescription(data.offer));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        socket.emit('answer', { to_sid: data.from_sid, answer });
    });

    socket.on('answer', async (data) => {
        console.log('Answer received from:', data.from_sid);
        await getPeerConnection(data.from_sid).setRemoteDescription(new RTCSessionDescription(data.answer));
    });

    socket.on('ice-candidate', (data) => {
        getPeerConnection(data.from_sid).addIceCandidate(new RTCIceCandidate(data.candidate));
    });

    socket.on('peer-left', (data) => {
        console.log('Peer left:', data.sid);
        if (peerConnections.has(data.sid)) {
            peerConnections.get(data.sid).close();
            peerConnections.delete(data.sid);
        }
        const videoContainer = document.getElementById(`container-${data.sid}`);
        if (videoContainer) {
            videoContainer.remove();
        }
    });
}

function createPeerConnection(sid, isInitiator) {
    if (peerConnections.has(sid)) return peerConnections.get(sid);

    const pc = new RTCPeerConnection(servers);
    peerConnections.set(sid, pc);

    localStream.getTracks().forEach(track => {
        pc.addTrack(track, localStream);
    });

    pc.ontrack = (event) => {
        addRemoteVideoStream(sid, event.streams[0]);
    };

    pc.onicecandidate = (event) => {
        if (event.candidate) {
            socket.emit('ice-candidate', { to_sid: sid, candidate: event.candidate });
        }
    };

    if (isInitiator) {
        pc.createOffer()
            .then(offer => pc.setLocalDescription(offer))
            .then(() => {
                socket.emit('offer', { to_sid: sid, offer: pc.localDescription });
            });
    }
    return pc;
}

function getPeerConnection(sid, isInitiator = false) {
    if (!peerConnections.has(sid)) {
        return createPeerConnection(sid, isInitiator);
    }
    return peerConnections.get(sid);
}

function addRemoteVideoStream(sid, stream) {
    const videoGrid = document.getElementById('video-grid');
    let videoContainer = document.getElementById(`container-${sid}`);
    if (!videoContainer) {
        videoContainer = document.createElement('div');
        videoContainer.classList.add('video-container');
        videoContainer.id = `container-${sid}`;

        const videoElement = document.createElement('video');
        videoElement.autoplay = true;
        videoElement.playsInline = true;

        const label = document.createElement('span');
        label.classList.add('video-label');
        label.textContent = `User ${sid.substring(0, 4)}`;

        videoContainer.appendChild(videoElement);
        videoContainer.appendChild(label);
        videoGrid.appendChild(videoContainer);
        videoElement.srcObject = stream;
    }
}

function addControlListeners() {
    const micBtn = document.getElementById('mic-btn');
    const cameraBtn = document.getElementById('camera-btn');
    const hangupBtn = document.getElementById('hangup-btn');

    micBtn.addEventListener('click', () => {
        const audioTrack = localStream.getTracks().find(track => track.kind === 'audio');
        audioTrack.enabled = !audioTrack.enabled;
        micBtn.innerHTML = audioTrack.enabled ? '<i class="fas fa-microphone"></i>' : '<i class="fas fa-microphone-slash"></i>';
    });

    cameraBtn.addEventListener('click', () => {
        const videoTrack = localStream.getTracks().find(track => track.kind === 'video');
        videoTrack.enabled = !videoTrack.enabled;
        cameraBtn.innerHTML = videoTrack.enabled ? '<i class="fas fa-video"></i>' : '<i class="fas fa-video-slash"></i>';
    });

    hangupBtn.addEventListener('click', () => {
        for (const pc of peerConnections.values()) {
            pc.close();
        }
        peerConnections.clear();
        if(socket) socket.disconnect();
        window.location.href = `/chat/${conversationId}`;
    });
}
