const emotion = /(?:\[\s*(?:neutral|joy|happy|sad(?:ness)?|anger|angry|surprise[d]?|disgust(?:ed)?|fear|afraid|love|playful|question|heartbeat|quiet|tongue|blush|star|heart|dizzy|sweat|cry|excited|smile|laugh|平静|开心|生气|难过|惊讶|害羞|得意)\s*\]|【\s*(?:情绪|表情)\s*[:：][^】\r\n]{1,40}】|\[\s*(?:emotion|expression|情绪|表情)\s*[:：][^\]\r\n]{1,40}\])/gi;
const stageDirection = /(?:（([^（）\r\n]{1,50})）|\(([^()\r\n]{1,50})\)|(?<!\*)\*([^*\r\n]{1,50})\*(?!\*))/g;
const action = /^(?:(?:轻轻|轻|微微|悄悄|小声|压低声音|低声|突然|慢慢|一边|假装|忍不住|略微)\s*)*(?:歪头|歪着头|歪了歪头|探头|凑近|靠近|眨眼|眨了眨眼|眨眨眼|甩尾巴|摆尾|摇尾|尾巴|摊手|叉腰|翻白眼|白了一眼|清嗓子|清清嗓子|捂嘴|捂住嘴|叹气|吸气|深吸|倒吸|瞪眼|瞪大|皱眉|扬眉|挑眉|挑了挑眉|蹙眉|转头|回头|摇头|点头|抬头|低头|鼓腮|鼓起|吐舌|吐了吐舌|哼了一声|哼哼|偷笑|坏笑|轻笑|笑眯眯|笑了笑|笑出声|脸红|捂脸|挠头|搓手|搓搓手|拍桌|拍了拍|拍打|揉揉|抱臂|缩成|张嘴|张大嘴|打哈欠|沉默片刻|愣住|愣了一下|喷笑|喷了|whispers?\b|laughs?\b|sighs?\b|smiles?\b|nods?\b|blushes?\b|chuckles?\b|giggles?\b)/i;

export function petDisplayText(text: string): string {
  return text.replace(emotion, '').replace(stageDirection, (match, chinese, ascii, emphasized) => (
    action.test((chinese ?? ascii ?? emphasized).trim()) ? '' : match
  )).replace(/\*\*([^*\r\n]+)\*\*/g, '$1').replace(/[ \t]{2,}/g, ' ').trim();
}
