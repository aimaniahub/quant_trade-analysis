import { Redis } from '@upstash/redis';

/**
 * Upstash Redis client for Next.js (Edge & Node.js runtimes).
 * Automatically resolves environment variables configured via Vercel Upstash integration.
 */
let redisClient: Redis | null = null;

export function getUpstashRedis(): Redis | null {
  if (redisClient) return redisClient;

  const url =
    process.env.redisupstashfyers_KV_REST_API_URL ||
    process.env.UPSTASH_REDIS_REST_URL ||
    process.env.KV_REST_API_URL ||
    process.env.NEXT_PUBLIC_UPSTASH_REDIS_REST_URL;

  const token =
    process.env.redisupstashfyers_KV_REST_API_TOKEN ||
    process.env.UPSTASH_REDIS_REST_TOKEN ||
    process.env.KV_REST_API_TOKEN ||
    process.env.NEXT_PUBLIC_UPSTASH_REDIS_REST_TOKEN;

  if (!url || !token) {
    return null;
  }

  try {
    redisClient = new Redis({
      url,
      token,
    });
    return redisClient;
  } catch (err) {
    console.warn('[Upstash Redis] Failed to initialize client:', err);
    return null;
  }
}
