import { Box, Button, Flex, IconButton, Text } from "@chakra-ui/react";
import { FiMonitor, FiSliders, FiRefreshCw } from "react-icons/fi";
import { useEffect, useState, PointerEvent } from "react";
import { useScreenCaptureContext } from "@/context/screen-capture-context";
import { CropRegion, clampCrop } from "@/utils/screen-vision";
import {
  PopoverRoot,
  PopoverTrigger,
  PopoverContent,
  PopoverBody,
} from "@/components/ui/popover";

const selectStyle = {
  width: "100%",
  background: "#1f2937",
  color: "#f9fafb",
  border: "1px solid #4b5563",
  borderRadius: 6,
  padding: 6,
};

function ScreenSettings({ onDescribe }: { onDescribe?: () => Promise<void> }) {
  const capture = useScreenCaptureContext();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<CropRegion | null>(null);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const point = (event: PointerEvent<HTMLImageElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };
  const regionTo = (end: { x: number; y: number }) =>
    anchor
      ? {
          x: Math.min(anchor.x, end.x),
          y: Math.min(anchor.y, end.y),
          width: Math.abs(anchor.x - end.x),
          height: Math.abs(anchor.y - end.y),
        }
      : null;
  const region = draft || capture.crop;
  const frame = capture.lastFrame?.metadata;
  const age = frame
    ? Math.max(0, Math.floor((now - Date.parse(frame.captured_at)) / 1000))
    : 0;
  const refresh = async () => {
    setBusy(true);
    try {
      await capture.captureScreen();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Box color="gray.100" fontSize="sm">
      <Flex align="center" justify="space-between" mb="2">
        <Text fontWeight="bold">屏幕视觉</Text>
        <Text color={capture.isStreaming ? "green.300" : "gray.400"}>
          {capture.isStreaming ? "已开启" : "已关闭"}
        </Text>
      </Flex>
      <Text color="gray.300" mb="3">
        开启后，发文字或说话时附带当前画面。关闭会停止采集并清除预览；每次启动默认关闭。
      </Text>
      <label>
        观察目标
        <select
          aria-label="观察目标"
          style={selectStyle}
          value={capture.selectedSource}
          disabled={capture.isStarting}
          onChange={(event) => capture.selectSource(event.target.value)}
        >
          <option value="">
            {window.electron ? "主显示器（默认）" : "开启时由系统选择"}
          </option>
          {capture.sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.kind === "window" ? "窗口" : "屏幕"} · {source.name}
            </option>
          ))}
        </select>
      </label>
      <Button
        variant="ghost"
        color="gray.100"
        size="xs"
        onClick={() => capture.loadSources()}
        my="1"
      >
        刷新目标列表
      </Button>
      <Text color="gray.400" fontSize="xs" mb="2">
        切换目标会关闭采集，请再点屏幕按钮开启。
      </Text>
      <Flex gap="2" mb="3">
        <label style={{ flex: 1 }}>
          图片细节
          <select
            aria-label="图片细节"
            style={selectStyle}
            value={capture.settings.maxEdge}
            onChange={(event) =>
              capture.updateSettings({ maxEdge: Number(event.target.value) })
            }
          >
            <option value={1280}>轻量 · 1280</option>
            <option value={1600}>均衡 · 1600</option>
            <option value={1920}>清晰 · 1920</option>
            <option value={2560}>精细 · 2560</option>
          </select>
        </label>
        <label style={{ flex: 1 }}>
          图片格式
          <select
            aria-label="图片格式"
            style={selectStyle}
            value={capture.settings.format}
            onChange={(event) =>
              capture.updateSettings({
                format: event.target.value as "image/png" | "image/jpeg",
              })
            }
          >
            <option value="image/png">PNG · 文字</option>
            <option value="image/jpeg">JPEG · 画面</option>
          </select>
        </label>
      </Flex>
      {capture.error && (
        <Text role="alert" color="red.300" mb="2">
          {capture.error}
        </Text>
      )}
      {capture.preview ? (
        <Box
          position="relative"
          border="1px solid"
          borderColor="gray.600"
          borderRadius="md"
          overflow="hidden"
        >
          <img
            alt="屏幕预览，拖动框选要看的区域"
            src={capture.preview}
            draggable={false}
            style={{
              display: "block",
              width: "100%",
              cursor: "crosshair",
              touchAction: "none",
              userSelect: "none",
            }}
            onPointerDown={(event) => {
              if (event.button !== 0 || !capture.isStreaming) return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              setAnchor(point(event));
              setDraft(null);
            }}
            onPointerMove={(event) => {
              if (anchor) setDraft(regionTo(point(event)));
            }}
            onPointerUp={(event) => {
              if (!anchor) return;
              capture.setCrop(clampCrop(regionTo(point(event))));
              setAnchor(null);
              setDraft(null);
            }}
            onPointerCancel={() => {
              setAnchor(null);
              setDraft(null);
            }}
          />
          {region && (
            <Box
              pointerEvents="none"
              position="absolute"
              border="2px solid #4ade80"
              bg="green.400/15"
              left={`${region.x * 100}%`}
              top={`${region.y * 100}%`}
              width={`${region.width * 100}%`}
              height={`${region.height * 100}%`}
            />
          )}
        </Box>
      ) : (
        <Box bg="gray.800" p="5" textAlign="center" borderRadius="md">
          {capture.isStreaming
            ? "点击刷新预览查看画面"
            : "屏幕已关闭，不采集画面"}
        </Box>
      )}
      <Flex gap="2" align="center" my="2" flexWrap="wrap">
        <Button
          size="xs"
          color="gray.100"
          disabled={!capture.isStreaming || busy}
          onClick={refresh}
        >
          <FiRefreshCw />
          刷新预览
        </Button>
        <Button
          size="xs"
          color="gray.100"
          borderColor="gray.600"
          variant="outline"
          disabled={!capture.crop}
          onClick={() => capture.setCrop(null)}
        >
          恢复全图
        </Button>
        {onDescribe && (
          <Button
            size="xs"
            colorPalette="green"
            disabled={!capture.isStreaming || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onDescribe();
              } finally {
                setBusy(false);
              }
            }}
          >
            描述当前画面
          </Button>
        )}
      </Flex>
      <Text color="gray.300" fontSize="xs">
        {capture.crop
          ? "仅发送绿色框内区域；先裁剪，再缩放。"
          : "在预览上拖动，可框选要读的小字或局部。"}
      </Text>
      <Text fontSize="xs" color={age > 10 ? "orange.300" : "gray.400"} mt="1">
        {frame
          ? `最近采集 ${age} 秒前 · ${frame.width}×${frame.height} · 采集 ${frame.capture_ms}ms`
          : "尚无本次设置的截图；发送消息时会重新采集。"}
      </Text>
      {capture.isStreaming && (
        <Text
          fontSize="xs"
          color="gray.400"
          truncate
          title={capture.sourceName}
        >
          {capture.sourceName}
        </Text>
      )}
    </Box>
  );
}

export function ScreenControls({
  compact = false,
  onDescribe,
}: {
  compact?: boolean;
  onDescribe?: () => Promise<void>;
}) {
  const capture = useScreenCaptureContext();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (open) capture.loadSources();
    (window.api as any)?.updateComponentHover?.("screen-controls", open);
    return () =>
      (window.api as any)?.updateComponentHover?.("screen-controls", false);
  }, [open]);
  const active = capture.isStreaming || capture.isStarting;
  const toggle = () => {
    if (active) capture.stopCapture();
    else {
      setOpen(true);
      void capture.startCapture();
    }
  };
  return (
    <Flex
      align="center"
      gap="1"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <IconButton
        aria-label={active ? "关闭屏幕视觉" : "开启屏幕视觉"}
        aria-pressed={active}
        title={active ? "屏幕视觉已开启，点击关闭" : "屏幕视觉已关闭，点击开启"}
        onClick={toggle}
        bg={active ? "green.600" : "gray.600"}
        color="white"
        width={compact ? "28px" : "50px"}
        minW={compact ? "28px" : "50px"}
        height={compact ? "28px" : "50px"}
        borderRadius={compact ? "md" : "12px"}
      >
        <FiMonitor size={compact ? 16 : 24} />
      </IconButton>
      <PopoverRoot
        open={open}
        onOpenChange={(details) => setOpen(details.open)}
        positioning={{ placement: "top-end" }}
      >
        <PopoverTrigger asChild>
          <IconButton
            aria-label="屏幕视觉设置"
            title="选择屏幕、预览和局部框选"
            size="xs"
            variant="ghost"
            color="gray.300"
          >
            <FiSliders />
          </IconButton>
        </PopoverTrigger>
        <PopoverContent
          bg="gray.900"
          borderColor="gray.600"
          width="min(420px, calc(100vw - 24px))"
          zIndex={5000}
        >
          <PopoverBody
            maxH="min(600px, calc(100vh - 24px))"
            overflowY="auto"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <ScreenSettings onDescribe={onDescribe} />
          </PopoverBody>
        </PopoverContent>
      </PopoverRoot>
    </Flex>
  );
}
