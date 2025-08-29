let localStream;
let remoteStream;
let peerConnection;
let socket;
let otherUserId;
let conversationId;

const servers = {
    iceServers: [
        {
            urls: ['stun:stun1.l.google.com:19302', 'stun:stun2.l.google.com:19302'],
        },
    ],
};

async function init(convoId, currentUserId, otherId) {
    conversationId = convoId;
    otherUserId = otherId;
    socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);

    // --- Get local media ---
    try {
        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        document.getElementById('local-video').srcObject = localStream;
    } catch (error) {
        console.error("Error accessing media devices.", error);
        alert("Could not access your camera and microphone. Please check permissions.");
        return;
    }

    setupSocketListeners();

    // If otherUserId is present, this client is the initiator
    if (otherUserId) {
        // Find the SID of the other user to send a direct call
        // This is a simplification. A real app would have a more robust user/SID mapping.
        // For now, we'll emit to the room and the other client will pick it up.
        console.log("Attempting to call user in room:", conversationId);
        createPeerConnection();
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);

        socket.emit('call-user', {
            offer,
            to: conversationId, // Emitting to the conversation room
        });
    }

    addControlListeners();
}

function setupSocketListeners() {
    socket.on('call-made', async (data) => {
        console.log("Receiving call...", data);
        // Callee receives the offer
        if (!otherUserId) { // This client is the callee
            createPeerConnection();
            await peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);

            socket.emit('make-answer', {
                answer,
                to: data.sid, // Send answer back directly to the caller's SID
            });
        }
    });

    socket.on('answer-made', async (data) => {
        console.log("Answer received.", data);
        // Caller receives the answer
        if (otherUserId) {
            await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
        }
    });

    socket.on('ice-candidate', (data) => {
        if (peerConnection) {
            peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
        }
    });
}

function createPeerConnection() {
    peerConnection = new RTCPeerConnection(servers);

    remoteStream = new MediaStream();
    document.getElementById('remote-video').srcObject = remoteStream;

    localStream.getTracks().forEach(track => {
        peerConnection.addTrack(track, localStream);
    });

    peerConnection.ontrack = (event) => {
        event.streams[0].getTracks().forEach(track => {
            remoteStream.addTrack(track);
        });
    };

    peerConnection.onicecandidate = (event) => {
        if (event.candidate) {
            socket.emit('ice-candidate', {
                candidate: event.candidate,
                to: conversationId, // Broadcast to the room
            });
        }
    };
}

function addControlListeners() {
    const micBtn = document.getElementById('mic-btn');
    const cameraBtn = document.getElementById('camera-btn');
    const hangupBtn = document.getElementById('hangup-btn');

    micBtn.addEventListener('click', () => {
        const audioTrack = localStream.getTracks().find(track => track.kind === 'audio');
        if (audioTrack.enabled) {
            audioTrack.enabled = false;
            micBtn.innerHTML = '<i class="fas fa-microphone-slash"></i>';
            micBtn.classList.remove('active');
        } else {
            audioTrack.enabled = true;
            micBtn.innerHTML = '<i class="fas fa-microphone"></i>';
            micBtn.classList.add('active');
        }
    });

    cameraBtn.addEventListener('click', () => {
        const videoTrack = localStream.getTracks().find(track => track.kind === 'video');
        if (videoTrack.enabled) {
            videoTrack.enabled = false;
            cameraBtn.innerHTML = '<i class="fas fa-video-slash"></i>';
            cameraBtn.classList.remove('active');
        } else {
            videoTrack.enabled = true;
            cameraBtn.innerHTML = '<i class="fas fa-video"></i>';
            cameraBtn.classList.add('active');
        }
    });

    hangupBtn.addEventListener('click', () => {
        if (peerConnection) {
            peerConnection.close();
        }
        // Redirect back to the chat or home
        window.location.href = `/chat/${conversationId}`;
    });
}
