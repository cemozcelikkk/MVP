/**
 * Açılış keşif sahnesi - haritanın ÜSTÜNDE duran, kendi scroll'u olan tam
 * ekran bir katman. Harita ve panel arkada normal şekilde kurulur (bbox
 * isteği, pinler, store'lar hiç beklemez); hero yalnızca önlerinde durur.
 *
 * Scroll ilerlemesi (0→1) TEK bir `--p` CSS değişkenine yazılır; tüm
 * paralaks, başlık geçişi, soru sırası ve vizör açılışı `index.css`teki
 * `.hero-*` kurallarında bu değişkenden türetilir (React her karede yeniden
 * render ETMEZ). İlerleme 1'e ulaştığında vizör tüm ekranı açmış olur ve
 * `onEnter` hero'yu kaldırır - arkadaki harita zaten tam görünür, geçiş
 * dikişsizdir.
 */
import { Droplets, Route, Zap } from "lucide-react";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { useMapDataStore } from "../store/useMapDataStore";
import { BrandMark } from "./AppTopBar";

interface Props {
  onEnter: () => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function ExploreHero({ onEnter }: Props) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const onEnterRef = useRef(onEnter);
  onEnterRef.current = onEnter;

  const count = useMapDataStore((s) => s.features.length);

  useEffect(() => {
    const scroller = scrollerRef.current;
    const stage = stageRef.current;
    if (!scroller || !stage) return;
    scroller.focus({ preventScroll: true }); // Space/PageDown hemen sahneyi ilerletsin

    let frame = 0;
    let entered = false;
    const update = () => {
      frame = 0;
      const max = scroller.scrollHeight - scroller.clientHeight;
      const progress = max > 0 ? Math.min(1, Math.max(0, scroller.scrollTop / max)) : 0;
      stage.style.setProperty("--p", progress.toFixed(4));
      if (progress >= 0.995 && !entered) {
        entered = true;
        onEnterRef.current();
      }
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  function travelToMap() {
    const scroller = scrollerRef.current;
    if (!scroller || prefersReducedMotion()) {
      onEnterRef.current();
      return;
    }
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
  }

  return (
    <div
      ref={scrollerRef}
      tabIndex={-1}
      data-testid="explore-hero"
      aria-label="KaravanTR'ye hoş geldin"
      role="region"
      className="fixed inset-0 z-50 overflow-y-auto overscroll-contain outline-none [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div className="h-[340svh]">
        <div
          ref={stageRef}
          className="hero-stage sticky top-0 h-[100svh] overflow-hidden text-text-on-dark"
          style={{
            background:
              "linear-gradient(180deg, rgb(var(--map-bg)) 0%, rgb(var(--surface-dark)) 58%, color-mix(in srgb, rgb(var(--accent-earth)) 60%, rgb(var(--surface-dark))) 100%)",
          }}
        >
          <Contours />
          <div
            className="hero-layer absolute right-[14%] top-[16%] hidden h-24 w-24 rounded-full sm:block"
            style={{ "--depth": -50, backgroundColor: "rgb(var(--surface-primary))" } as CSSProperties}
            aria-hidden
          />
          <Ridges />

          {/* --- Üst şerit: marka + atla --- */}
          <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-between px-5 pt-5 sm:px-10 sm:pt-8">
            <div className="flex items-center gap-2.5">
              <BrandMark className="h-8 w-8 text-accent-sage" />
              <span className="font-display text-2xl font-medium">KaravanTR</span>
            </div>
            <button
              type="button"
              onClick={() => onEnterRef.current()}
              className="min-h-touch rounded-full px-4 text-sm font-medium text-text-on-dark-muted transition-colors hover:text-text-on-dark"
            >
              Haritaya geç
            </button>
          </div>

          {/* --- Sahne 1: soru --- */}
          <div className="hero-title absolute inset-x-0 top-[17svh] z-10 px-5 sm:top-[19svh] sm:px-10 lg:px-16">
            <h1 className="font-display text-[clamp(3rem,8.4vw,8.25rem)] font-normal leading-[0.94] tracking-[-0.025em] [text-wrap:balance] max-w-[11ch]">
              Yarın sabah nerede uyanacaksın?
            </h1>
            <p className="mt-6 max-w-[34rem] text-[17px] leading-relaxed text-text-on-dark-muted sm:text-lg">
              Karavancıların sahada işaretlediği kamp, su ve park noktaları. Suyu, elektriği ve yolun durumunu
              gitmeden öğren.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
              <button
                type="button"
                onClick={travelToMap}
                data-testid="hero-enter"
                className="min-h-touch rounded-full bg-surface-primary px-6 text-[15px] font-semibold text-text-primary transition-colors hover:bg-surface-raised"
              >
                Noktaları keşfet
              </button>
              {count > 0 ? (
                <p className="text-sm text-text-on-dark-muted">
                  Şu an haritada <span className="font-semibold tabular-nums text-text-on-dark">{count}</span> nokta
                  işaretli
                </p>
              ) : null}
            </div>
          </div>

          {/* --- Sahne 2: bir noktada bakılan üç şey --- */}
          <div className="hero-questions pointer-events-none absolute inset-x-0 top-[16svh] z-10 px-5 sm:top-[20svh] sm:px-10 lg:px-16">
            <ul className="flex max-w-[40rem] flex-col gap-7 sm:gap-9">
              <HeroQuestion step="--q1" icon={<Droplets size={22} />} title="Su var mı?">
                Hortum takılabilen temiz su olan noktalar kartta işaretli.
              </HeroQuestion>
              <HeroQuestion step="--q2" icon={<Zap size={22} />} title="Elektrik var mı?">
                220V bağlantı sunan yerleri tek bakışta ayırırsın.
              </HeroQuestion>
              <HeroQuestion step="--q3" icon={<Route size={22} />} title="Yol karavanı taşır mı?">
                Asfalt, toprak ya da taşlık. Dik rampa ve 4x4 gereken yerler ayrıca belirtilir.
              </HeroQuestion>
            </ul>
          </div>

          <p className="hero-cue absolute inset-x-0 bottom-6 z-10 text-center text-[13px] text-text-on-dark-muted">
            Kaydırdıkça harita açılır
          </p>
        </div>
      </div>
    </div>
  );
}

function HeroQuestion({
  step,
  icon,
  title,
  children,
}: {
  step: string;
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="hero-question flex gap-4 sm:gap-5" style={{ "--q": `var(${step})` } as CSSProperties}>
      <span className="mt-1.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent-sage/20 text-accent-sage sm:mt-3">
        {icon}
      </span>
      <div>
        <p className="font-display text-[clamp(2rem,4.6vw,3.75rem)] leading-[1.02] tracking-[-0.02em]">{title}</p>
        <p className="mt-2 max-w-[30rem] text-base leading-relaxed text-text-on-dark-muted">{children}</p>
      </div>
    </li>
  );
}

/**
 * Sırt silüetleri - arkadan öne dört katman, her biri farklı hızda aşağı
 * iner (`--depth` px, p=1'de). Renkler tasarım tokenlarından; öndeki katman
 * harita zeminiyle aynı, böylece sahne aşağıda haritanın rengine oturur.
 */
const RIDGE_LAYERS: { d: string; fill: string; height: string; depth: number }[] = [
  {
    d: "M0 190 L110 120 L190 150 L300 70 L400 128 L520 96 L610 140 L720 60 L840 132 L930 104 L1040 150 L1150 84 L1260 126 L1360 98 L1440 124 L1440 320 L0 320 Z",
    fill: "rgb(var(--border-dark))",
    height: "46svh",
    depth: 60,
  },
  {
    d: "M0 210 L140 150 L240 184 L360 118 L470 176 L600 138 L700 190 L820 126 L960 186 L1080 144 L1200 196 L1320 150 L1440 172 L1440 320 L0 320 Z",
    fill: "rgb(var(--surface-dark-raised))",
    height: "36svh",
    depth: 140,
  },
  {
    d: "M0 230 L160 190 L290 222 L420 170 L560 214 L690 186 L820 226 L980 176 L1120 218 L1260 188 L1440 214 L1440 320 L0 320 Z",
    fill: "rgb(var(--surface-dark))",
    height: "26svh",
    depth: 230,
  },
  {
    d: "M0 262 C180 236 320 248 480 256 C640 264 760 232 920 240 C1080 248 1260 270 1440 250 L1440 320 L0 320 Z",
    fill: "rgb(var(--map-bg))",
    height: "16svh",
    depth: 320,
  },
];

function Ridges() {
  return (
    <div className="hero-ridges pointer-events-none absolute inset-0" aria-hidden>
      {RIDGE_LAYERS.map((layer) => (
        <svg
          key={layer.depth}
          viewBox="0 0 1440 320"
          preserveAspectRatio="xMidYMax slice"
          className="hero-layer absolute inset-x-0 bottom-[-2px] w-full"
          style={{ height: layer.height, "--depth": layer.depth } as CSSProperties}
        >
          <path d={layer.d} fill={layer.fill} />
        </svg>
      ))}
    </div>
  );
}

/**
 * Topografik eş yükselti eğrileri - haritanın diline gönderme. Deterministik
 * (her render aynı): sinüs toplamıyla bozulmuş iç içe kapalı eğriler.
 */
function contourPath(cx: number, cy: number, radius: number, seed: number): string {
  const points: string[] = [];
  const steps = 72;
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * Math.PI * 2;
    const wobble = 1 + 0.12 * Math.sin(3 * t + seed) + 0.06 * Math.sin(5 * t - seed * 1.7) + 0.04 * Math.cos(7 * t + seed * 0.6);
    const x = cx + Math.cos(t) * radius * 1.35 * wobble;
    const y = cy + Math.sin(t) * radius * wobble;
    points.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  return points.join(" ") + " Z";
}

const CONTOURS = Array.from({ length: 9 }, (_, i) => contourPath(1060, 250, 40 + i * 46, 0.9 + i * 0.35));

function Contours() {
  return (
    <svg
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMid slice"
      className="hero-layer pointer-events-none absolute inset-0 h-full w-full"
      style={{ "--depth": -90 } as CSSProperties}
      aria-hidden
    >
      <g fill="none" stroke="rgb(var(--accent-sage))" strokeWidth="1" opacity="0.16">
        {CONTOURS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
    </svg>
  );
}
