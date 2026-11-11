import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { ChakraProvider, defaultSystem, Box, Text } from "@chakra-ui/react";
import {
  ScreenCaptureProvider,
  useScreenCaptureContext,
} from "../src/renderer/src/context/screen-capture-context";
import { ScreenControls } from "../src/renderer/src/components/screen/screen-controls";
import { wsService } from '../src/renderer/src/services/websocket-service';

const sandbox = window as any;
sandbox.requests = 0;
sandbox.socketMessages = [];
sandbox.connectScreenTestSocket = () => {
  class Socket {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    readyState = 0;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    constructor() {
      sandbox.testSocket = this;
      setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
    }
    send(data: string) { sandbox.socketMessages.push(JSON.parse(data)); }
    close() { this.readyState = 3; }
  }
  sandbox.WebSocket = Socket;
  wsService.connect('ws://synthetic-test');
};
sandbox.requestScreenTestFrame = (request_id: string, permission_token: string) => {
  sandbox.testSocket.onmessage({ data: JSON.stringify({ type: 'screen-capture-request', request_id, permission_token }) });
};
sandbox.mockStreams = [];
sandbox.electron = {
  ipcRenderer: {
    invoke: async () => [
      {
        id: "screen:test",
        name: "合成测试屏幕",
        kind: "screen",
        primary: true,
        width: 3840,
        height: 2160,
      },
      { id: "window:test", name: "合成测试窗口", kind: "window" },
    ],
  },
};
Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
  value: async () => {
    sandbox.requests += 1;
    const canvas = document.createElement("canvas");
    canvas.width = 3840;
    canvas.height = 2160;
    const ctx = canvas.getContext("2d")!;
    const draw = () => {
      ctx.fillStyle = "#102030";
      ctx.fillRect(0, 0, 3840, 2160);
      ctx.fillStyle = "#10b981";
      ctx.fillRect(960, 540, 1920, 1080);
      ctx.fillStyle = "#ffffff";
      ctx.font = "100px Arial";
      ctx.fillText("SCREEN TEST 4826", 1100, 1000);
    };
    draw();
    const stream = canvas.captureStream(2);
    const timer = setInterval(draw, 400);
    const track = stream.getVideoTracks()[0];
    const stop = track.stop.bind(track);
    track.stop = () => {
      clearInterval(timer);
      stop();
    };
    sandbox.mockStreams.push(stream);
    if (sandbox.slowAcquire)
      await new Promise((resolve) => {
        sandbox.finishAcquire = resolve;
      });
    return stream;
  },
  configurable: true,
});

function Probe() {
  const context = useScreenCaptureContext();
  useEffect(() => {
    sandbox.vision = context;
  }, [context]);
  return (
    <Box
      position="fixed"
      bottom="30px"
      right="30px"
      bg="gray.800"
      borderRadius="xl"
      p="5"
    >
      <Text mb="2" color="white">
        桌宠屏幕视觉 · 合成画面测试
      </Text>
      <ScreenControls
        compact
        onDescribe={async () => {
          sandbox.describeFrame = await context.captureScreen();
        }}
      />
    </Box>
  );
}
createRoot(document.getElementById("root")!).render(
  <ChakraProvider value={defaultSystem}>
    <ScreenCaptureProvider>
      <Probe />
    </ScreenCaptureProvider>
  </ChakraProvider>,
);
