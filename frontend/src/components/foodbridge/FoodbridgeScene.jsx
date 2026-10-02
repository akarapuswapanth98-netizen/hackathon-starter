/**
 * Immersive 3D FoodBridge demo scene (react-three-fiber + drei).
 *
 * Data contract — nothing is hard-coded:
 * - restaurant at origin; surplus meal count from the live surplus lot.
 * - shelters laid out via layoutShelters() using REAL distance_km from the
 *   allocation response when present (else haversine); scene spacing is
 *   illustrative and every label says so.
 * - six agents light up in the backend's REAL event order; per-step delays
 *   derive from real timestamp deltas via buildReplaySchedule() (staged
 *   replay — backend returns all events at once on completion).
 * - beams are drawn ONLY to shelters in the live allocation array,
 *   thickness/color scaled by that shelter's real allocated meals.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { Canvas, useFrame } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import {
  AGENT_ORDER,
  AGENT_COLORS,
  buildReplaySchedule,
  layoutAgents,
  layoutShelters,
  workflowSpanMs,
} from './layout'

const REST_POS = [0, 0, 0]

function AgentOrb({ info, index, revealed, isCurrent, detail, retried }) {
  const ref = useRef()
  const active = index < revealed
  const color = AGENT_COLORS[info.name] || '#4b5563'
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.getElapsedTime()
    // Gentle float; current agent pulses. Cheap: scale only, no geometry churn.
    const base = active ? 1.15 : 0.9
    const pulse = isCurrent ? Math.sin(t * 4) * 0.12 : Math.sin(t * 1.2 + index) * 0.03
    const s = base + pulse
    ref.current.scale.setScalar(s)
  })
  return (
    <group position={info.position}>
      <mesh ref={ref}>
        <sphereGeometry args={[0.42, 20, 20]} />
        <meshStandardMaterial
          color={active ? color : '#334155'}
          emissive={active ? color : '#000000'}
          emissiveIntensity={active ? (isCurrent ? 1.6 : 0.9) : 0}
        />
      </mesh>
      {active && (
        <pointLight color={color} intensity={isCurrent ? 6 : 2.5} distance={6} />
      )}
      {/* Retry cue: distinct orange ring on Verification when retry_count > 0 */}
      {info.name === 'verification' && retried && active && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.68, 0.05, 10, 32]} />
          <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={1.2} />
        </mesh>
      )}
      <Html center distanceFactor={14} style={{ pointerEvents: 'none' }}>
        <div
          data-testid={`agent-label-${info.name}`}
          style={{
            fontSize: '10px',
            fontWeight: 700,
            color: active ? '#0f172a' : '#64748b',
            background: active ? '#fff' : 'rgba(255,255,255,0.75)',
            border: `2px solid ${active ? color : '#cbd5e1'}`,
            borderRadius: '8px',
            padding: '2px 6px',
            whiteSpace: 'nowrap',
          }}
        >
          {info.name}
          {info.name === 'verification' && retried ? ` ↻×${retried}` : ''}
          {isCurrent ? ' ●' : active ? ' ✓' : ''}
        </div>
      </Html>
      {isCurrent && detail && (
        <Html center position={[0, 1.1, 0]} distanceFactor={14} style={{ pointerEvents: 'none', zIndexRange: [20, 0] }}>
          <div
            data-testid="agent-detail"
            style={{
              fontSize: '11px',
              maxWidth: '240px',
              background: 'rgba(15,23,42,0.92)',
              color: '#f8fafc',
              borderRadius: '8px',
              padding: '6px 9px',
              border: `1px solid ${color}`,
            }}
          >
            <strong>{info.name}</strong>: {detail}
          </div>
        </Html>
      )}
    </group>
  )
}

function Beam({ from, to, meals, maxMeals, index }) {
  const pulse = useRef()
  const { midpoint, quaternion, length, radius, color } = useMemo(() => {
    const a = new THREE.Vector3(...from)
    const b = new THREE.Vector3(...to)
    const dir = b.clone().sub(a)
    const len = dir.length()
    const mid = a.clone().add(b).multiplyScalar(0.5)
    const quat = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      dir.clone().normalize(),
    )
    const frac = maxMeals > 0 ? meals / maxMeals : 0
    const r = 0.05 + frac * 0.16
    // Color scales with real quantity: small = amber, large = green.
    const c = frac > 0.66 ? '#059669' : frac > 0.33 ? '#84cc16' : '#f59e0b'
    return { midpoint: mid, quaternion: quat, length: len, radius: r, color: c }
  }, [from, to, meals, maxMeals])

  useFrame(({ clock }) => {
    if (!pulse.current) return
    const t = (clock.getElapsedTime() * 0.35 + index * 0.27) % 1
    const a = new THREE.Vector3(...from)
    const b = new THREE.Vector3(...to)
    pulse.current.position.lerpVectors(a, b, t)
    pulse.current.position.y += 0.35
  })

  return (
    <group>
      <mesh position={midpoint} quaternion={quaternion}>
        <cylinderGeometry args={[radius, radius, length, 10, 1, true]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.85}
          transparent
          opacity={0.75}
        />
      </mesh>
      <mesh ref={pulse}>
        <sphereGeometry args={[0.14, 12, 12]} />
        <meshStandardMaterial color="#ffffff" emissive={color} emissiveIntensity={2} />
      </mesh>
    </group>
  )
}

function InitializingRig() {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (ref.current) ref.current.rotation.y = clock.getElapsedTime() * 0.8
  })
  return (
    <group position={[0, 2.2, 0]}>
      <mesh ref={ref}>
        <torusGeometry args={[1.4, 0.08, 10, 40]} />
        <meshStandardMaterial color="#2563eb" emissive="#2563eb" emissiveIntensity={1.4} />
      </mesh>
      <Html center distanceFactor={14} style={{ pointerEvents: 'none' }}>
        <div data-testid="scene-initializing" style={labelStyle}>
          ⏳ Workflow initializing… waiting for real agent_events (nothing faked)
        </div>
      </Html>
    </group>
  )
}

const labelStyle = {
  fontSize: '11px',
  background: 'rgba(15,23,42,0.9)',
  color: '#fff',
  padding: '5px 9px',
  borderRadius: '8px',
  whiteSpace: 'nowrap',
}

function SceneContents({
  restaurant,
  shelters,
  surplusMeals,
  allocation,
  agentEvents,
  workflowStatus,
  retryCount,
  error,
  initializing,
  animate,
}) {
  const laid = useMemo(
    () => layoutShelters({ restaurant, shelters, allocation }),
    [restaurant, shelters, allocation],
  )
  const agents = useMemo(() => layoutAgents(), [])
  const schedule = useMemo(() => buildReplaySchedule(agentEvents || []), [agentEvents])
  const [revealed, setRevealed] = useState(0)

  // Staged replay of REAL events. Timers derive from actual timestamp deltas.
  useEffect(() => {
    setRevealed(0)
    if (!schedule.length) return undefined
    if (!animate) {
      setRevealed(schedule.length)
      return undefined
    }
    let cancelled = false
    const timers = []
    let acc = 0
    schedule.forEach((step, i) => {
      acc += step.delayMs
      timers.push(
        setTimeout(() => {
          if (!cancelled) setRevealed(i + 1)
        }, acc),
      )
    })
    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
  }, [schedule, animate])

  const revealedEvents = useMemo(
    () => schedule.slice(0, revealed).map((s) => s.event),
    [schedule, revealed],
  )
  const currentEvent = revealedEvents[revealedEvents.length - 1] || null
  const revealedAgents = useMemo(() => {
    const order = new Map()
    revealedEvents.forEach((e) => {
      if (!order.has(e.agent)) order.set(e.agent, e)
    })
    return order
  }, [revealedEvents])

  const hasMatching = revealedEvents.some((e) => e.agent === 'matching')
  const hasVerification = revealedEvents.some((e) => e.agent === 'verification')
  const failed = workflowStatus === 'failed'
  const showBeams = hasMatching && hasVerification && !failed && (allocation || []).length > 0
  const showEmpty = hasVerification && !failed && (allocation || []).length === 0
  const maxMeals = Math.max(1, ...(allocation || []).map((a) => a.meals || 0))
  const allocById = useMemo(
    () => new Map((allocation || []).map((a) => [a.shelter_id, a])),
    [allocation],
  )
  const spanMs = useMemo(() => workflowSpanMs(agentEvents || []), [agentEvents])

  return (
    <>
      <ambientLight intensity={0.75} />
      <directionalLight position={[6, 10, 4]} intensity={1.1} />
      {/* Ground plane + grid: modest geometry, laptop-GPU friendly */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]}>
        <circleGeometry args={[16, 40]} />
        <meshStandardMaterial color="#e2e8f0" />
      </mesh>
      <gridHelper args={[32, 32, '#94a3b8', '#cbd5e1']} position={[0, 0, 0]} />

      {/* Restaurant at origin */}
      <group position={REST_POS}>
        <mesh position={[0, 0.6, 0]}>
          <boxGeometry args={[1.5, 1.2, 1.5]} />
          <meshStandardMaterial color="#059669" emissive="#059669" emissiveIntensity={0.25} />
        </mesh>
        <mesh position={[0, 1.45, 0]}>
          <coneGeometry args={[1.15, 0.7, 4]} />
          <meshStandardMaterial color="#065f46" />
        </mesh>
        <Html center position={[0, 2.3, 0]} distanceFactor={14} style={{ pointerEvents: 'none' }}>
          <div data-testid="scene-restaurant" style={{ ...labelStyle, background: '#065f46' }}>
            🍲 {restaurant?.name || 'Restaurant'} · {surplusMeals ?? '?'} meals
          </div>
        </Html>
      </group>

      {/* Shelters — illustrative positions, REAL distance labels */}
      {laid.map(({ shelter, allocation: alloc, realKm, position }) => (
        <group key={shelter.id} position={position}>
          <mesh position={[0, 0.45, 0]}>
            <boxGeometry args={[1, 0.9, 1]} />
            <meshStandardMaterial
              color={alloc ? '#2563eb' : '#94a3b8'}
              emissive={alloc ? '#2563eb' : '#000000'}
              emissiveIntensity={alloc ? 0.55 : 0}
            />
          </mesh>
          {alloc && (
            <pointLight color="#2563eb" intensity={2} distance={5} position={[0, 1.5, 0]} />
          )}
          <Html center position={[0, 1.5, 0]} distanceFactor={14} style={{ pointerEvents: 'none' }}>
            <div
              data-testid={`scene-shelter-${shelter.id}`}
              style={{
                ...labelStyle,
                background: alloc ? '#1e3a8a' : 'rgba(15,23,42,0.75)',
                border: alloc ? '1px solid #93c5fd' : 'none',
              }}
            >
              🏠 {shelter.name} · {realKm != null ? `${realKm.toFixed(1)} km (actual)` : 'dist ?'}
              {alloc ? ` · +${alloc.meals} meals` : ''}
              <div style={{ fontSize: '9px', opacity: 0.75 }}>scene spacing illustrative, not to scale</div>
            </div>
          </Html>
        </group>
      ))}

      {/* Six agents */}
      {agents.map((info, i) => {
        const ev = revealedAgents.get(info.name)
        const isCurrent = currentEvent?.agent === info.name && revealedEvents[revealedEvents.length - 1] === ev
        return (
          <AgentOrb
            key={info.name}
            info={info}
            index={i}
            revealed={revealedAgents.has(info.name) ? AGENT_ORDER.indexOf(info.name) + 1 : 0}
            isCurrent={!!(ev && currentEvent && currentEvent.agent === info.name && ev.detail === currentEvent.detail)}
            detail={ev?.detail}
            retried={info.name === 'verification' ? retryCount || 0 : 0}
          />
        )
      })}

      {/* Beams — only to shelters REALLY allocated, after matching+verification */}
      {showBeams &&
        laid
          .filter((l) => allocById.has(l.shelter.id))
          .map((l, i) => (
            <Beam
              key={l.shelter.id}
              from={[REST_POS[0], 1.2, REST_POS[2]]}
              to={[l.position[0], 0.9, l.position[2]]}
              meals={allocById.get(l.shelter.id).meals}
              maxMeals={maxMeals}
              index={i}
            />
          ))}

      {/* Failed workflow: clear error marker, never silent */}
      {failed && hasVerification && (
        <group position={[0, 4.6, 0]}>
          <mesh>
            <octahedronGeometry args={[0.7, 0]} />
            <meshStandardMaterial color="#dc2626" emissive="#dc2626" emissiveIntensity={1.2} />
          </mesh>
          <Html center position={[0, 1.2, 0]} distanceFactor={14} style={{ pointerEvents: 'none' }}>
            <div data-testid="scene-failed" style={{ ...labelStyle, background: '#991b1b' }}>
              ❌ Workflow failed — no meals routed{error?.code ? ` (${error.code})` : ''}
            </div>
          </Html>
        </group>
      )}

      {/* Empty allocation */}
      {showEmpty && (
        <group position={[0, 4.6, 0]}>
          <Html center distanceFactor={14} style={{ pointerEvents: 'none' }}>
            <div data-testid="scene-empty" style={{ ...labelStyle, background: '#92400e' }}>
              🔍 No matches found — allocation is empty
            </div>
          </Html>
        </group>
      )}

      {initializing && <InitializingRig />}

      {/* Replay provenance note as a tiny 3D-attached label */}
      {schedule.length > 0 && (
        <Html position={[0, -0.02, 9.5]} distanceFactor={16} style={{ pointerEvents: 'none' }}>
          <div data-testid="scene-replay-note" style={{ fontSize: '10px', color: '#475569', background: 'rgba(255,255,255,0.85)', padding: '3px 8px', borderRadius: '6px', whiteSpace: 'nowrap' }}>
            Staged replay of {schedule.length} real events · backend span {spanMs}ms · order preserved
          </div>
        </Html>
      )}
    </>
  )
}

export const __testables = { REST_POS }

/**
 * Canvas wrapper. HUD is DOM outside this component so it renders instantly
 * even while the replay animation is still playing.
 */
export default function FoodbridgeScene(props) {
  const { animate = true } = props
  return (
    <div data-testid="foodbridge-scene" style={{ position: 'relative', width: '100%', height: '480px', borderRadius: '12px', overflow: 'hidden', background: '#0f172a' }}>
      <Canvas dpr={[1, 1.75]} camera={{ position: [9, 8, 11], fov: 48 }} data-testid="foodbridge-canvas">
        <color attach="background" args={['#0f172a']} />
        <SceneContents {...props} animate={animate} />
        <OrbitControls enableDamping makeDefault maxPolarAngle={Math.PI / 2.1} minDistance={4} maxDistance={30} />
      </Canvas>
      <div className="small" style={{ position: 'absolute', bottom: '8px', right: '10px', color: 'rgba(255,255,255,0.65)', zIndex: 4 }}>
        drag to orbit · scroll to zoom
      </div>
    </div>
  )
}
