import { useState } from 'react';
import { useWebSocket } from '@/context/websocket-context';
import { useAiState } from '@/context/ai-state-context';
import { useInterrupt } from '@/components/canvas/live2d';
import { useChatHistory } from '@/context/chat-history-context';
import { useVAD } from '@/context/vad-context';
import { useMediaCapture } from '@/hooks/utils/use-media-capture';
import { toaster } from '@/components/ui/toaster';
import { authorizeScreenImages } from '@/utils/screen-vision';

export function useTextInput() {
  const [inputText, setInputText] = useState('');
  const [isComposing, setIsComposing] = useState(false);
  const wsContext = useWebSocket();
  const { aiState } = useAiState();
  const { interrupt } = useInterrupt();
  const { appendHumanMessage } = useChatHistory();
  const { stopMic, autoStopMic } = useVAD();
  const { captureAllMedia } = useMediaCapture();

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputText(e.target.value);
  };

  const sendText = async (text: string, requireScreen = false) => {
    if (!text.trim() || !wsContext) return;
    if (aiState === 'thinking-speaking') {
      interrupt();
    }

    const { images } = authorizeScreenImages({ images: await captureAllMedia() });
    if (requireScreen && !images.some((image) => image.source === 'screen')) {
      toaster.create({ title: '屏幕未开启或截图失败，请先开启并刷新预览。', type: 'info', duration: 3000 });
      return;
    }

    appendHumanMessage(text.trim());
    wsContext.sendMessage({
      type: 'text-input',
      text: text.trim(),
      images,
    });

    if (autoStopMic) stopMic();
  };

  const handleSend = async () => {
    await sendText(inputText);
    setInputText('');
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (isComposing) return;

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCompositionStart = () => setIsComposing(true);
  const handleCompositionEnd = () => setIsComposing(false);

  return {
    inputText,
    setInputText: handleInputChange,
    handleSend,
    sendText,
    handleKeyPress,
    handleCompositionStart,
    handleCompositionEnd,
  };
}
