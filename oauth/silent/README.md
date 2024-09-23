# Silent auth

This is very similar to passkeys semantically, but with a better signup user
experience. In passkeys, the idea is the user has some way of storing a private
key. To register they provide a public key, we create a passkey_account. To sign
in they prove they have the corresponding private key.

In theory, this should be possible without coordinating with the user at all,
supposing we are satisfied with the physical security compromises that would
come with that flow. In our case, we want security implications similar to
keeping a physical journal, so we ignore attacks that require the physical
device.

Unfortunately, webauthn is very concerned with that attack method and thus
requires prompting well beyond what we want. This leads to a really confusing
interface, the inability to provide a single button to sign in / sign up, and
generally an experience so complicated that it'd be better not to offer it all.

So, when we know the users platform does not support a clean passkey flow (such
as webauthn), but does offer storage and a secure random generator, the client
instead negotiates "Silent" authorization.

We describe how to do silent authorization assuming a minimal number of
cryptographic primitives are available (e.g., SHA512). Where more primitives
are available they should be used.

## Key Generation

Generating an 4096 bit RSA key pair, taken from
https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.186-5.pdf
section 5.1 and appendex A.1.3

relevant attacks to be aware of:
https://crypto.stanford.edu/%7Edabo/papers/RSA-survey.pdf

The hardest part is generating large prime numbers. See the preliminary section

Let `nlen` be the intended bit length of the modulus `n`, which must be 4096
Let `e` be the intended RSA public exponent, which must be 65537

1. Generate a prime `p` of length `nlen/2` (2048) bits (see Appendix 1), such
   that `p-1` is relatively prime to `e` (65537)
2. Generate a prime `q` of length `nlen/2` (2048) bits (see Appendix 1), such
   that `|p-q| >= 2^(nlen/2-100)`, i.e., `|p-q| >= 2^2048-100`, i.e.,
   `|p-q| >= 2^1948`, and `q-1` is relatively prime to `e` (65537)
3. Let `n=p*q`.
4. Compute `phi=lcm(p-1, q-1)` via `phi=|(p-1)*(q-1)|/gcd(p-1, q-1)`.
5. If `phi <= e` (65337), go to step 1
6. Compute `d=e^-1 mod phi` by solving `de=1 mod phi` for `d` through
   the extended euclidean algorithm (correct for sign) (see Appendix 2)
7. If `d` is less than or equal to `2^(nlen/2)` (2048), i.e., `d<=2^2048`, go to step 1
8. If `d` is greater than `phi`, fail (this should be false by construction)
9. The public key is now `(n, e)` and the private key is `d`. Store the public
   and private key locally. Discard all other values.

## Key Signing

The client requests challenges from the server. The server produces these
challenges by signing a value with the clients public key and expecting the
client to return proof they determined the value that was signed within a time
window.

The server needs to pad this value to ensure the client is the only one who can
decrypt the message.

The server, given `n` (4096 bit), `e` (the value 65537), and a message `m`
(length must be less than `n - 2 * hLen - 2`, i.e., `4096 - 2 * 512 - 2`,
i.e., `3070` bits, and must not be guessable) produces a challenge `c` by
computing

- Let `M = OAEP(m)`, the padded message. See Appendix 3a for details
- `c = M^e (mod n)`

Associate `m` with a public identifier, expiring within a short period of time.
The server provides the public identifier and the challenge; the client must
return the public identifier and the response to the challenge to prove they
have the private key.

## Key Verification

The client will complete registration or login on the server after requesting a
challenge by decoding `c` and returning the original message `m` to the server.

The client must ensure the message is padded with the correct scheme to prevent
leaking the private key

NOTE: to not leak the private key the seeds within M are arbitrary; even if the
server is choosing the seeds, it will not let them determine the private key. It
is the server that needs those seeds to be random.

1. generate a random value `r` of length 4096 bits (blinding)
2. compute `q = r^-1 (mod n)` (see Appendix 2); if r and n are not coprime, go to step 1
3. decode `rM = ((r^e)c)^d (mod n)` (blinding)
4. compute `M = rMq (mod n)` (unblind)
5. compute `m = OAEP^-1(M)`, the unpadded message (message used padding scheme) (see Appendix 3b)
6. return `m`

## Appendix

### Appendix 1: Generating a prime (FIPS 186-5 appendix A.1.3) from a secure random number source

1. Generate a random number `p` of length `nlen/2` (2048) bits
2. Set the two most significant bits in `p` to 1 (ensures `p` is large)

- specifically, `p` is now at least 2^2048 + 2^2047 >= sqrt(2) \* (2^2047), satisfying 4.4

3.  Set the least significant bit in `p` to 1 (ensures `p` is odd)
4.  If `gcd(p-1, e) != 1`, i.e., `gcd(p-1, 65537) != 1`, i.e., `p-1` and `65537` are not coprime,
    go to step 1
5.  If any preconditions are set on `p` (typically, `p` is a certain distance from `q`), check
    them here and go to step 1 if they are not met
6.  Check `p` is probably prime via 44 Miller-Rabin tests (error probability = 2^-144) (FIPS 186-5 Appendix B.3)

    - a. Let `a` be the largest integer such that `2^a` divides `p-1`
      - this can be done by repeatedly dividing `p-1` by 2 until the result is odd
    - b. Let `m=(p-1)/2^a`
    - c. intentionally omitted
    - d. for `i=1` to `44` do

          - i. Generate a random number `b` with 2048 bits
          - ii. if `b<=1` or `b>=p-1`, goto 6.d.i [without incrementing i]
          - iii. let `z = b^m (mod p)`
          - iv. if `z=1` or `z=p-1`, continue (test satisfied)
          - v. for `j=1` to `a-1` do
            - 1. reassign `z = z^2 (mod p)`
            - 2. if `(z=p-1)`, continue to the next iteration of the outer loop (test satisfied)
            - 3. if `(z=1)`, return `p` is composite
          - vi. return `p` is composite

      e. `p` is probably prime with error probability 2^-144

### Appendix 2: Modular Multiplicative Inverse

#### Appendix 2a: Using the Extended Euclidean Algorithm

Given `d, e, phi`, where `e` is prime, compute `d = e^-1 mod phi` as follows:

1. Using the Extended Euclidean Algorithm with `a=e` and `b=phi`, let integers
   `x`, `y` be such that `e*x + b*phi = 1`
2. Hence, `e*x = 1 - b*phi`
3. Hence, `e*x = 1 mod phi`
4. Thus, `d=x`

#### Appendix 2b: Extended Euclidean Algorithm

Given `a, b`, compute `x, y` such that `a*x + b*y = gcd(a, b)` as follows:

https://en.wikipedia.org/wiki/Extended_Euclidean_algorithm

```
function extended_gcd(a, b)
    (old_r, r) := (a, b)
    (old_s, s) := (1, 0)
    (old_t, t) := (0, 1)

    while r ≠ 0 do
        quotient := old_r div r
        (old_r, r) := (r, old_r − quotient × r)
        (old_s, s) := (s, old_s − quotient × s)
        (old_t, t) := (t, old_t − quotient × t)

    output "Bézout coefficients:", (old_s, old_t)
    output "greatest common divisor:", old_r
    output "quotients by the gcd:", (t, s)
    return (old_s, old_t)
```

### Appendix 3: Optimal asymmetric encryption padding (OAEP)

RSA is by default deterministic. Among other things, this means that the same
plaintext is encrypted to the same ciphertext every time, allowing the generation
of lookup tables. Furthermore, an adversary can learn things about the private key
if given a decryption oracle for arbitrary ciphertexts.

To prevent the first, we incorporate randomness. To prevent the second, we impose
restrictions on the type of ciphertexts that can be decrypted. The algorithm used
is called Optimal Asymmetric Encryption Padding (OAEP). Note that blinding is still
required to protect against timing attacks, even with OAEP.

Let `LabelHash` be `SHA512('')`, i.e., the byte string whose hex representation is
`cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e`

- EXPLANATION: It isn't important exactly what this label hash is except that it is
  agreed upon, of the correct length, and doesn't have any special patterns.
  To show we didn't choose one that is special, we take a recognizable constant.
  It is important that adversaries cannot choose this value.

#### Appendix 3a: Convert `M` to `EM` via OAEP

https://en.wikipedia.org/wiki/Optimal_asymmetric_encryption_padding

This is a function defined in such a way that we can prove certain properties about
it when used as the padding scheme for RSA. Described here we assume 4096-bit RSA
with SHA512 as the hash function. It is defined as follows:

Let `M` be the message to be padded and `EM` the padded message

- If `len(M) > 382`, fail
- Let `PS` consist of `382 - len(M)` zero bytes, representing the padding string
- Let `DB = LabelHash || PS || 0x01 || M`, representing the data block
- Let `seed` be a random 64-byte value
- Generate `dbMask = MGF1(seed, 447)`, i.e., `(512 - 64 - 1)` bits of mask data
  (see Appendix 3c)
- Let `maskedDB = DB XOR dbMask`
- Let `seedMask = MGF1(maskedDB, 64)`, i.e., `64` bytes of mask data
- Let `maskedSeed = seed XOR seedMask`
- return `EM = 0x00 || maskedSeed || maskedDB`

#### Appendix 3b: Convert `EM` to `M` via OAEP

- If `EM` is not exactly 512 bytes, fail
- If the first bit is not `0x00`, fail
- Let `maskedSeed` be the next 64 bytes
- Let `maskedDB` be the remaining 447 bytes
- Let `seedMask = MGF1(maskedDB, 64)`, i.e., `64` bytes of mask data
- Let `seed = maskedSeed XOR seedMask`, the seed
- Let `dbMask = MGF1(seed, 447)`, i.e., `(512 - 64 - 1)` bits of mask data
- Let `DB = maskedDB XOR dbMask`, the data block
- If the first 64 bytes of `DB` are not `LabelHash`, fail
- Verify the next byte is a 0 byte
- Skip 0x00 bytes until the first 1 byte; if none, fail
- return the remaining bytes, `M`, the message

#### Appendix 3c: MGF1

MGF1 is a deterministic function that converts an input value (a "seed") into
another value ("mask") of a specific length. We always use SHA512 as the hash
function for MGF1

https://en.wikipedia.org/wiki/Mask_generation_function

1. if the requested output size is over 512 \* (2^32), fail
2. let `T` be an empty octet string
3. let `counter` be 0
4. let `C` be the counter value as a 4 octet string (big-endian, unsigned)
5. add `SHA512(seed + C)` to `T`
6. increment `counter`
7. if `T` is less than the requested length of `len`, goto 2
8. return the first `len` octets of `T`
